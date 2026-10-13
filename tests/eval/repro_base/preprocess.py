"""Passages -> sentences -> entities."""
import re

import spacy

NLP = spacy.load("en_core_web_sm")


def split_sentences(passage: str) -> list[str]:
    # sentence boundaries: periods, exclamation and question marks
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", passage) if s.strip()]


def entities(sentence: str) -> list[str]:
    return [ent.text for ent in NLP(sentence).ents]
