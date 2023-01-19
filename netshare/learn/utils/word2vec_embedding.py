import itertools
import itertools
import os
from typing import Any, Dict, List, NamedTuple

import numpy as np
import pandas as pd
from annoy import AnnoyIndex
from gensim.models import Word2Vec
from sklearn.neighbors import NearestNeighbors

from netshare.utils.logger import logger


class annoyTypeDescription(NamedTuple):
    annoy_type: AnnoyIndex
    annoy_dict: Dict[int, Any]


def word2vec_train(
    df,
    out_dir,
    model_name,
    word2vec_cols,
    word2vec_size,
    annoy_n_trees,
    force_retrain=False,  # retrain from scratch
    model_test=False,
):
    model_path = os.path.join(out_dir, "{}_{}.model".format(model_name, word2vec_size))

    if os.path.exists(model_path) and not force_retrain:
        logger.info("Loading Word2Vec pre-trained model...")
        model = Word2Vec.load(model_path)
    else:
        logger.info("Training Word2Vec model from scratch...")
        sentences = []
        for row in range(0, len(df)):
            sentence = [
                str(df.at[row, col]) for col in [c.column for c in word2vec_cols]
            ]
            sentences.append(sentence)

        model = Word2Vec(
            sentences=sentences, size=word2vec_size, window=5, min_count=1, workers=10
        )
        model.save(model_path)
    logger.info(f"Word2Vec model is saved at {model_path}")

    return model_path


def get_word2vec_type_col(word2vec_cols: List[Any]) -> Dict[str, List[str]]:
    dict_type_cols: Dict[str, List[str]] = {}
    for col in word2vec_cols:
        type = col.encoding.split("_")[1]
        if type not in dict_type_cols:
            dict_type_cols[type] = []
        dict_type_cols[type].append(col.column)
    return dict_type_cols


def build_annoy_dictionary_word2vec(
    df: pd.DataFrame,
    model_path: str,
    word2vec_cols: List[Any],
    word2vec_size: int,
    n_trees: int,
) -> Dict[str, annoyTypeDescription]:

    dict_type_annDictPair: Dict[str, annoyTypeDescription] = {}

    model = Word2Vec.load(model_path)
    wv = model.wv

    # type : [cols]
    # ("ip": ["srcip", "dstip"])
    # "port": ["srcport", "dstport"]
    # "proto": ["proto"]
    dict_type_cols = get_word2vec_type_col(word2vec_cols)
    logger.info(dict_type_cols)

    for type, cols in dict_type_cols.items():
        type_set = set(
            list(itertools.chain.from_iterable([list(df[col]) for col in cols]))
        )
        type_ann = AnnoyIndex(word2vec_size, "angular")
        type_dict = {}
        index = 0

        for ele in type_set:
            type_ann.add_item(index, get_vector(model, str(ele), norm_option=True))
            type_dict[index] = ele
            index += 1
        type_ann.build(n_trees)

        dict_type_annDictPair[type] = annoyTypeDescription(
            annoy_type=type_ann, annoy_dict=type_dict
        )

    logger.info("Finish building Angular trees...")

    return dict_type_annDictPair


def get_original_obj(ann, vector, dic):
    obj_list = ann.get_nns_by_vector(vector, 1, search_k=-1, include_distances=False)

    return dic[obj_list[0]]


def get_original_objs(ann, vectors, dic):
    res = []
    for vector in vectors:
        obj_list = ann.get_nns_by_vector(
            vector, 1, search_k=-1, include_distances=False
        )
        res.append(dic[obj_list[0]])
    return res


def get_vector(model, word, norm_option=False):
    all_words_str = list(model.wv.vocab.keys())

    # Privacy-related
    # If word not in the vocabulary, replace with nearest neighbor
    # Suppose that protocol is covered
    #   while very few port numbers are out of range
    if word not in all_words_str:
        # print(f"{word} not in dict")
        all_words = []
        for ele in all_words_str:
            if ele.isdigit():
                all_words.append(int(ele))
        all_words = np.array(all_words).reshape((-1, 1))
        nbrs = NearestNeighbors(n_neighbors=1, algorithm="ball_tree").fit(all_words)
        distances, indices = nbrs.kneighbors([[int(word)]])
        nearest_word = str(all_words[indices[0][0]][0])
        model.init_sims()
        return model.wv.word_vec(nearest_word, use_norm=norm_option)
    else:
        model.init_sims()
        return model.wv.word_vec(word, use_norm=norm_option)
