"""Thesaurus for a clicked word: WordNet synonyms for the sense the word has in its sentence, put in
the same form as the word ("drawn" → "depicted"). Offline; WordNet and a part-of-speech tagger
(~18 MB) download into tools/nltk_data the first time.
"""
import os
import re

import lemminflect
import nltk

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "nltk_data")
nltk.data.path.insert(0, DATA)
_POS = {"NOUN": "n", "VERB": "v", "ADJ": "a", "ADV": "r"}


def _wordnet():
    from nltk.corpus import wordnet as wn
    try:
        wn.ensure_loaded()
    except LookupError:
        nltk.download("wordnet", download_dir=DATA, quiet=True)
    return wn


def _tag_in(sentence, word):
    """Penn tag of `word` as used in `sentence` (NNS, VBN, ...), or None."""
    try:
        nltk.data.find("taggers/averaged_perceptron_tagger_eng")
    except LookupError:
        nltk.download("averaged_perceptron_tagger_eng", download_dir=DATA, quiet=True)
    toks = re.findall(r"[\w′'-]+|[^\w\s]", sentence)
    return next((t for w, t in nltk.pos_tag(toks) if w == word), None)


_UPOS = {"N": "NOUN", "V": "VERB", "J": "ADJ", "R": "ADV"}


def _forms(word):
    """→ [(part of speech, lemma, Penn tag of `word`)], e.g. drawn → [(VERB, draw, VBN), (ADJ, drawn, JJ)]."""
    w = word.lower()
    out = []
    for upos, lemmas in lemminflect.getAllLemmas(w).items():
        for lem in lemmas:
            tag = next((t for t, fs in lemminflect.getAllInflections(lem, upos=upos).items() if w in fs), None)
            out.append((upos, lem, tag))
    return out or [(None, w, None)]


def synonyms(word, sentence="", senses=5, per_sense=6):
    """→ [{pos, gloss, words}] for the most common senses of `word`, each synonym inflected like `word`.
    With the sentence, only senses with the word's part of speech there are offered."""
    wn = _wordnet()
    seen, out = {word.lower()}, []
    forms = _forms(word)
    tag = _tag_in(sentence, word) if sentence else None
    upos = _UPOS.get((tag or " ")[0])
    if upos:
        lem = (lemminflect.getLemma(word.lower(), upos=upos) or (word.lower(),))[0]
        forms = [(upos, lem, tag)]
    for upos, lem, tag in forms:
        for syn in wn.synsets(lem, pos=_POS.get(upos)):
            ws = []
            for l in syn.lemmas():
                s = l.name().replace("_", " ")
                if s.lower() == lem:
                    continue
                if tag and " " not in s:
                    inf = lemminflect.getInflection(s, tag=tag)
                    s = inf[0] if inf else s
                if word[:1].isupper():
                    s = s[:1].upper() + s[1:]
                if s.lower() not in seen:
                    seen.add(s.lower())
                    ws.append(s)
            if ws:
                out.append({"pos": (upos or "").lower(), "gloss": syn.definition(), "words": ws[:per_sense]})
            if len(out) >= senses:
                return out
    return out
