#!/usr/bin/env python3

# Copyright  2017  Jian Wang
# License: Apache 2.0.

import os
import argparse
import sys
import math
from collections import defaultdict

parser = argparse.ArgumentParser(description="This script turns the words into the sparse feature representation, "
                                             "using features from rnnlm/choose_features.py.",
                                 epilog="E.g. " + sys.argv[0] + " --unigram-probs=exp/rnnlm/unigram_probs.txt "
                                        "data/rnnlm/vocab/words.txt exp/rnnlm/features.txt "
                                        "> exp/rnnlm/word_feats.txt",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("--unigram-probs", type=str, default='', required=True,
                    help="Specify the file containing unigram probs.")
parser.add_argument("vocab_file", help="Path for vocab file")
parser.add_argument("features_file", help="Path for features file")

args = parser.parse_args()


# read the voab
# return the vocab, which is a dict mapping the word to a integer id.
def read_vocab(vocab_file):
    vocab = {}
    with open(vocab_file, 'r', encoding="utf-8") as f:
        for line in f:
            fields = line.split()
            assert len(fields) == 2
            if fields[0] in vocab:
                sys.exit(sys.argv[0] + ": duplicated word({0}) in vocab: {1}"
                                       .format(fields[0], vocab_file))
            vocab[fields[0]] = int(fields[1])

    # check there is no duplication and no gap among word ids
    sorted_ids = sorted(vocab.values())
    for idx, id in enumerate(sorted_ids):
        assert idx == id

    return vocab


# read the unigram probs
# return a list of unigram_probs, indexed by word id
def read_unigram_probs(unigram_probs_file):
    unigram_probs = []
    with open(unigram_probs_file, 'r', encoding="utf-8") as f:
        for line in f:
            fields = line.split()
            assert len(fields) == 2
            idx = int(fields[0])
            if idx >= len(unigram_probs):
                unigram_probs.extend([None] * (idx - len(unigram_probs) + 1))
            unigram_probs[idx] = float(fields[1])

    for prob in unigram_probs:
        assert prob is not None

    return unigram_probs


# read the features
# return a dict with following items:

#   feats['constant'] is None if there is no constant feature used, else
#                     a 2-tuple (feat_id, value), e.g. (1, 1.0).
#   feats['special'] is a dict whose key is special words and value is the feat_id
#   feats['unigram'] is a tuple with (feat_id, entropy, scale)
#   feats['length']  is a int represents feat_id
#
#   feats['match']
#   feats['initial']
#   feats['final']
#   feats['word']    is a dict with key is ngram, value is feat_id for each type
#                    of ngram feature respectively.
#   feats['min_ngram_order'] is a int represents min-ngram-order
#   feats['max_ngram_order'] is a int represents max-ngram-order
def read_features(features_file):
    feats = {}
    feats['constant'] = None
    feats['special'] = {}
    feats['match'] = {}
    feats['initial'] = {}
    feats['final'] = {}
    feats['word'] = {}
    feats['min_ngram_order'] = 10000
    feats['max_ngram_order'] = -1

    with open(features_file, 'r', encoding="utf-8") as f:
        for line in f:
            fields = line.split()
            assert(len(fields) in [2, 3, 4])

            feat_id = int(fields[0])
            feat_type = fields[1]
            if feat_type == 'constant':
                value = float(fields[2])
                feats['constant'] = (feat_id, value)
            elif feat_type == 'special':
                feats['special'][fields[2]] = feat_id
            elif feat_type == 'unigram':
                feats['unigram'] = (feat_id, float(fields[2]), float(fields[3]))
            elif feat_type == 'length':
                feats['length'] = feat_id
            elif feat_type in ['word', 'match', 'initial', 'final']:
                ngram = fields[2]
                feats[feat_type][ngram] = feat_id
                if feat_type == 'word':
                    continue
                elif feat_type in ['initial', 'final']:
                    order = len(ngram) + 1
                else:
                    order = len(ngram)
                if order > feats['max_ngram_order']:
                    feats['max_ngram_order'] = order
                if order < feats['min_ngram_order']:
                    feats['min_ngram_order'] = order
            else:
                sys.exit(sys.argv[0] + ": error feature type: {0}".format(feat_type))

    return feats

vocab = read_vocab(args.vocab_file)
unigram_probs = read_unigram_probs(args.unigram_probs)
feats = read_features(args.features_file)


def get_feature_list(word, idx):
    """Return a dict from feat_id to value (as int or float), e.g.
      { 0 -> 1.0, 100 -> 1 }
    """
    ans = defaultdict(int)  # the default is only used for character-ngram features.
    if idx == 0:
        return ans

    if feats['constant'] is not None:
        (feat_id, value) = feats['constant']
        ans[feat_id] = value

    if word in feats['special']:
        feat_id = feats['special'][word]
        ans[feat_id] = 1
        return ans   # return because words with the 'special' feature do
                     # not get any other features (except the constant
                     # feature).

    if 'unigram' in feats:
        feat_id = feats['unigram'][0]
        entropy = feats['unigram'][1]
        scale = feats['unigram'][2]
        logp = math.log(unigram_probs[idx])
        ans[feat_id] = (logp + entropy) * scale / entropy

    if 'length' in feats:
        feat_id = feats['length']
        ans[feat_id] = len(word)

    if word in feats['word']:
        feat_id = feats['word'][word]
        ans[feat_id] = 1

    for pos in range(len(word) + 1):  # +1 for EOW
        for order in range(feats['min_ngram_order'], feats['max_ngram_order'] + 1):
            start = pos - order + 1
            end = pos + 1

            if start < -1:
                continue

            if start < 0 and end > len(word):
                # 'word' feature, which we already match before
                continue
            elif start < 0:
                ngram_feats = feats['initial']
                start = 0
            elif end > len(word):
                ngram_feats = feats['final']
                end = len(word)
            else:
                ngram_feats = feats['match']
            if start >= end:
                continue

            feat = word[start:end]
            if feat in ngram_feats:
                feat_id = ngram_feats[feat]
                ans[feat_id] += 1
    return ans

for word, idx in sorted(vocab.items(), key=lambda x: x[1]):
    feature_list = get_feature_list(word, idx)
    print("{0}\t{1}".format(idx,
                            " ".join(["{0} {1}".format(f, v) for f, v in sorted(feature_list.items())])))


print(sys.argv[0] + ": made features for {0} words.".format(len(vocab)), file=sys.stderr)
