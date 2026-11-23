"""Conservative, local retrieval from the team's reviewed dialogue examples."""
from collections import Counter
import math
from pathlib import Path
import re
import sqlite3

from .lexicon import normalize, stem


BLOCKED_TOPICS = {"Память", "Контекст", "Счёт", "Инструкция", "Предпочтения", "Игра"}
STOP = set("я ты мы вы он она они у в на и а но же то вот это как что мне тебя меня тебе уже вообще очень пожалуйста".split())
ALIASES = {"че": "что", "чо": "что", "щас": "сейчас",
           "наконец-то": "наконец", "наконецто": "наконец", "экзамены": "экзамен",
           "делаешь": "занят", "делаеш": "занят", "готовить": "приготовить"}


def tokens(text):
    words = re.findall(r"[а-яa-z0-9]+(?:-[а-я]+)?", normalize(text))
    return [stem(ALIASES.get(word, word)) for word in words]


def key(text):
    return " ".join(tokens(text))


def signature(text):
    words = set(re.findall(r"[а-яa-z0-9]+", normalize(text)))
    # Do not transfer an answer across negation, people, quantities or time.
    people = "other" if words & {"друг", "подруга", "мама", "папа", "сестра", "брат", "он", "она", "они", "ему", "ей", "друга", "подруги"} else "self"
    addressee = bool(words & {"ты", "тебе", "твой", "твоя", "любишь", "умеешь"})
    numbers = tuple(re.findall(r"\d+", text))
    time = words & {"вчера", "сегодня", "завтра", "раньше", "сейчас", "потом"}
    negative = words & {"не", "нет", "без", "никогда", "ничего", "никто"}
    question = next((kind for kind, group in (
        ("why", {"почему", "отчего"}), ("purpose", {"зачем"}),
        ("where", {"куда", "где", "откуда"}), ("when", {"когда"}),
        ("quantity", {"сколько"}), ("definition", {"такое"}),
    ) if words & group), None)
    return people, addressee, numbers, time, negative, question


def context_fits(context, history):
    if not context:
        return True
    # Unstructured summaries and memory examples cannot safely supply live facts.
    chunks = list(re.finditer(r"«([^»]+)»", context))
    if not chunks or len(chunks) > 4:
        return False
    expected = []
    role = None
    end = 0
    for chunk in chunks:
        prefix = normalize(context[end:chunk.start()])
        if "бот" in prefix:
            role = "text"
        elif "человек" in prefix or "вопрос" in prefix:
            role = "question"
        if role is None:
            return False
        expected.append((role, key(chunk[1])))
        end = chunk.end()
    observed = [(role, key(turn.get(role, ""))) for turn in history[-2:]
                for role in ("question", "text")]
    if not history or len(expected) > len(observed):
        return False
    # Require the context to reach the most recent turn, with matching speaker.
    for start in range(len(observed) - len(expected) + 1):
        window = observed[start:start + len(expected)]
        if window == expected and start + len(expected) >= len(observed) - 1:
            return True
    return False


class Corpus:
    def __init__(self, path):
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute("SELECT value FROM corpus_metadata WHERE key='schema_version'").fetchone()
            if version is None or version[0] != "1":
                raise ValueError("Неподдерживаемая версия корпуса")
            self.rows = [dict(row) for row in db.execute(
                "SELECT r.*, s.filename FROM corpus_replies r JOIN corpus_sources s ON s.id=r.source_id WHERE r.approved=1")]
        finally:
            db.close()
        self.rows = [row for row in self.rows if row["topic"] not in BLOCKED_TOPICS]
        documents = [set(tokens(row["prompt"])) - STOP for row in self.rows]
        frequencies = Counter(word for document in documents for word in document)
        self.idf = {word: 1 + math.log((len(documents) + 1) / (count + 1)) for word, count in frequencies.items()}
        for row, document in zip(self.rows, documents):
            row["words"] = document
            row["key"] = key(row["prompt"])
            row["signature"] = signature(row["prompt"])

    def match(self, question, history=()):
        if len(question) > 4000 or re.search(r"[«»\"\n]", question):
            return None
        query = key(question)
        words = set(tokens(question)) - STOP
        query_signature = signature(question)
        matches = []
        for row in self.rows:
            if not context_fits(row["context"], history) or query_signature != row["signature"]:
                continue
            exact = query == row["key"]
            if exact:
                score = 1.0
            else:
                common = words & row["words"]
                if len(common) < 2 or len(words) < 2:
                    continue
                weight = lambda pool: sum(self.idf.get(word, 3.5) for word in pool)
                # Both sides must be covered; one shared topic is insufficient.
                coverage = weight(common) / max(weight(words), weight(row["words"]), 1)
                if coverage < .78:
                    continue
                score = 2 * weight(common) / (weight(words) + weight(row["words"]))
                if score < .84:
                    continue
            if row["context"]:
                score += .01
            matches.append((score, row))
        matches.sort(key=lambda item: (-item[0], item[1]["id"]))
        if not matches:
            return None
        score, row = matches[0]
        if len(matches) > 1 and score - matches[1][0] < .08 and row["answer"] != matches[1][1]["answer"]:
            return None
        return {"text": row["answer"], "id": row["id"], "topic": row["topic"],
                "source": row["filename"], "row": row["row_number"], "score": round(score, 4)}
