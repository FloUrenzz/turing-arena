"""Indexed lookup for the optional large set of standalone dialogue examples."""

from contextlib import closing
import hashlib
from pathlib import Path
import re
import sqlite3
import unicodedata


BASE_NAME = 'dialogue-combined-5350-v2.sqlite3'
EXPANSION_NAME = 'dialogue-expansion.sqlite3'
JURY_NAME = 'dialogue-jury.sqlite3'


def utterance_key(text):
    """Normalize chat punctuation and spacing while keeping words in order."""
    value = unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е')
    value = re.sub(r'(?<!\d),|,(?!\d)', ' ', value)
    return ' '.join(value.split()).rstrip(' .!?')


def lookup_key(normalized_text):
    return hashlib.sha256(normalized_text.encode('utf-8')).digest()[:16]


def expansion_uri(corpus_path, name=EXPANSION_NAME):
    """Keep explicitly selected custom corpora independent of the extra data."""
    path = Path(corpus_path).resolve()
    extension = path.with_name(name)
    if path.name == BASE_NAME and extension.is_file():
        return extension.as_uri() + '?mode=ro'
    return None


def find_expansion_reply(uri, question, *, keywords=False, source=EXPANSION_NAME):
    if not uri or len(question) > 400 or '\n' in question or '\r' in question:
        return None
    method, score = 'expansion', 1.0
    try:
        with closing(sqlite3.connect(uri, uri=True)) as db:
            row = db.execute('''
                SELECT u.id, s.topic, s.answer FROM utterances u
                JOIN scenarios s ON s.id = u.scenario_id WHERE u.lookup = ?
            ''', (lookup_key(utterance_key(question)),)).fetchone()
            if row is None and keywords:
                from .expansion_keywords import find_keyword_reply
                match = find_keyword_reply(db, question)
                if match is not None:
                    row, score = match[:3], match[3]
                    method = 'expansion-keywords'
    except sqlite3.Error:
        # The earlier corpus remains usable if the optional sidecar is missing or damaged.
        return None
    if row is None:
        return None
    identifier, topic, answer = row
    identifier_scope = method if source == EXPANSION_NAME else f'{source}:{method}'
    return {'text': answer, 'id': f'{identifier_scope}:{identifier}', 'topic': topic,
            'source': source, 'row': identifier, 'score': score,
            'review': 'generated', 'kind': 'scenario' if method == 'expansion-keywords' else 'reply',
            'method': method}


def find_expansion_topic(uri, question):
    if not uri:
        return None
    from .expansion_keywords import find_keyword_topic
    try:
        with closing(sqlite3.connect(uri, uri=True)) as db:
            return find_keyword_topic(db, question)
    except sqlite3.Error:
        return None
