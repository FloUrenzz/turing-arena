import json
import re
import sqlite3
from pathlib import Path


def normalize(text):
    return text.casefold().replace("ё", "е")


def stem(word):
    if len(word) < 7:
        return word
    for ending in ("иями", "ами", "ями", "ого", "ему", "ому", "его", "ией", "иям",
                   "иях", "ию", "ия", "ие", "ии", "ов", "ев", "ей", "ам", "ям",
                   "ах", "ях", "ом", "ем", "ой", "ую", "ая", "яя", "ые", "ий", "ый",
                   "а", "я", "ы", "и", "у", "ю", "е", "о"):
        if word.endswith(ending) and len(word) - len(ending) >= 5:
            return word[:-len(ending)]
    return word


class Lexicon:
    def __init__(self, path):
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            self.concepts = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM concepts")}
            self.forms = {}
            for row in connection.execute("SELECT * FROM forms"):
                self.forms.setdefault(normalize(row["form"]), set()).add(row["concept"])
            for key, item in self.concepts.items():
                self.forms.setdefault(normalize(item["lemma"]), set()).add(key)
            self.facts = [dict(row) for row in connection.execute("SELECT * FROM facts")]
            self.groups = {}
            for row in connection.execute("SELECT * FROM groups"):
                self.groups.setdefault(row["category"], set()).add(row["concept"])
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.knowledge = {}
            if "knowledge" in tables:
                for row in connection.execute("SELECT * FROM knowledge"):
                    record = dict(row)
                    record["clauses"] = json.loads(record["clauses_json"])
                    record["attributes"] = json.loads(record["attributes_json"])
                    self.knowledge[record["id"]] = record
        finally:
            connection.close()
        self.stems = {}
        for form, ids in self.forms.items():
            if " " not in form and len(form) >= 7:
                self.stems.setdefault(stem(form), set()).update(ids)

    def mentions(self, text):
        text = normalize(text)
        found = []
        for form, ids in self.forms.items():
            pattern = r"(?<![а-яa-z])" + re.escape(form).replace(r"\ ", r"\s+") + r"(?![а-яa-z])"
            for match in re.finditer(pattern, text):
                found.extend((match.start(), key) for key in sorted(ids))
        for match in list(re.finditer(r"[а-яa-z]+", text))[:160]:
            word = match[0]
            if word not in self.forms and len(word) >= 7:
                ids = self.stems.get(stem(word), set())
                if len(ids) == 1:
                    found.append((match.start(), next(iter(ids))))
        return sorted(set(found))

    def find(self, text):
        return list(dict.fromkeys(key for _, key in self.mentions(text)))

    def fact(self, predicate, concept=None):
        return next((fact for fact in self.facts if fact["subject"] == "self"
                     and fact["predicate"] == predicate
                     and (concept is None or fact["object"] == concept)), None)

    def preferred(self, category):
        options = [fact for fact in self.facts if fact["subject"] == "self"
                   and fact["predicate"] == "likes"
                   and fact["object"] in self.groups.get(category, set())
                   and (fact["value"] or 0) > 0]
        return max(options, key=lambda row: (row["value"], row["id"]), default=None)

    def noun(self, concept, case="acc"):
        record = self.concepts[concept]
        return record.get(case) or record["lemma"]
