"""Conservative, local retrieval from the team's reviewed dialogue examples."""
from collections import Counter
import json
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


def speech_act(text):
    direct = r"^(?:а\s+|ну\s+)?(?:как\b|какой\b|какая\b|какие\b|какое\b|кто\b|что\b|чем\b|че\b|почему\b|зачем\b|где\b|куда\b|когда\b|сколько\b)"
    return "question" if "?" in text or re.search(direct, normalize(text).strip()) else "statement"


def literal_signature(text):
    """Keep quote boundaries and literal punctuation, not just sentence tokens."""
    matches = list(re.finditer(r'«([^»]*)»|"([^"]*)"', text))
    remainder = re.sub(r'«[^»]*»|"[^"]*"', "", text)
    if re.search(r'[«»"]', remainder):
        return None
    return tuple(" ".join(normalize(match[1] if match[1] is not None else match[2]).split()) for match in matches)


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
    return people, addressee, numbers, time, negative, question, speech_act(text)


def context_fits(context, history, turns=None):
    if turns is not None:
        expected = [("question" if turn["role"] == "user" else "text", (key(turn["text"]), speech_act(turn["text"]), literal_signature(turn["text"]))) for turn in turns]
        if not expected:
            return True
    elif not context:
        return True
    else:
        # Legacy contexts: only explicit quotes with an identifiable speaker.
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
            expected.append((role, (key(chunk[1]), speech_act(chunk[1]), literal_signature(chunk[1]))))
            end = chunk.end()
    observed = [(role, (key(turn.get(role, "")), speech_act(turn.get(role, "")), literal_signature(turn.get(role, "")))) for turn in history[-2:]
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
            reviewed = db.execute("SELECT value FROM corpus_metadata WHERE key='review_schema'").fetchone()
            if reviewed is not None and reviewed[0] != "1":
                raise ValueError("Неподдерживаемая версия проверки корпуса")
            reviews = {row["reply_id"]: dict(row) for row in db.execute("SELECT * FROM corpus_reviews")} if reviewed else {}
        finally:
            db.close()
        self.rows = [row for row in self.rows if row["id"] in reviews or row["topic"] not in BLOCKED_TOPICS]
        starters = []
        for row in self.rows:
            review = reviews.get(row["id"])
            row["review"] = review["decision"] if review else None
            row["context_turns"] = json.loads(review["context_turns_json"]) if review else None
            row["kind"] = "reply"
            # Reviewed dialogue examples contain both the antecedent and follow-up.
            # An explicit user/bot pair can also supply the preceding response;
            # it is still conditional on any turns before that pair.
            turns = row["context_turns"] or []
            for index in range(len(turns) - 1):
                user, bot = turns[index:index + 2]
                if user["role"] == "user" and bot["role"] == "bot" and len(bot["text"].encode("utf-16-le")) // 2 <= 300:
                    starter = dict(row)
                    starter.update(id=row["id"] + ":context:" + str(index), prompt=user["text"],
                                   answer=bot["text"], context="", context_turns=turns[:index], kind="context")
                    starters.append(starter)
        self.rows.extend(starters)
        documents = [set(tokens(row["prompt"])) - STOP for row in self.rows]
        frequencies = Counter(word for document in documents for word in document)
        self.idf = {word: 1 + math.log((len(documents) + 1) / (count + 1)) for word, count in frequencies.items()}
        for row, document in zip(self.rows, documents):
            row["words"] = document
            row["ordered"] = [word for word in tokens(row["prompt"]) if word not in STOP]
            row["key"] = key(row["prompt"])
            row["signature"] = signature(row["prompt"])
            row["literals"] = literal_signature(row["prompt"])

    def match(self, question, history=()):
        if len(question) > 4000 or "\n" in question:
            return None
        literals = literal_signature(question)
        if literals is None:
            return None
        query = key(question)
        words = set(tokens(question)) - STOP
        ordered = [word for word in tokens(question) if word not in STOP]
        query_signature = signature(question)
        matches = []
        for row in self.rows:
            if not context_fits(row["context"], history, row["context_turns"]) or query_signature != row["signature"]:
                continue
            if literals != row["literals"] or literals and query != row["key"]:
                continue
            # A small corpus does not establish that an unseen qualifier is harmless.
            # Preserve content words AND their order, including causal/event order.
            # Controlled aliases, inflections and omitted fillers still generalize.
            if ordered != row["ordered"]:
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
            if row["context"] or row["context_turns"]:
                score += .01
            matches.append((score, row))
        matches.sort(key=lambda item: (-item[0], item[1]["id"]))
        if not matches:
            return None
        score, row = matches[0]
        if any(score - other_score < .08 and row["answer"] != other["answer"] for other_score, other in matches[1:]):
            return None
        return {"text": row["answer"], "id": row["id"], "topic": row["topic"],
                "source": row["filename"], "row": row["row_number"], "score": round(score, 4),
                "review": row["review"], "kind": row["kind"]}
