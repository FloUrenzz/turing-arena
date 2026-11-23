"""Trace known-corpus routing and real Windows workers; not a blind quality test."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import initial_state
from arena.runtime import Runtime


def run():
    corpus = ROOT / "data" / "dialogue.sqlite3"
    db = ensure_demo_database()
    connection = sqlite3.connect(corpus)
    try:
        prompts = connection.execute("SELECT example_id,prompt FROM corpus_replies WHERE approved=1 ORDER BY row_number").fetchall()
    finally:
        connection.close()
    rows = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")):
        for identifier, prompt in prompts:
            base = generate(prompt, initial_state(), db)
            start = time.perf_counter()
            reply = generate(prompt, initial_state(), db, corpus_path=corpus)
            rows.append({"example_id": identifier, "prompt": prompt, "base_intent": base["intent"],
                         "reply": reply, "prepare_ms": round((time.perf_counter() - start) * 1000, 3)})
    controls = ["Почему после дождя иногда появляется радуга? Объясни простыми словами.",
                "Что бы ты посоветовал человеку, который впервые приехал в Астану зимой?",
                "Друг опоздал на встречу на полчаса и извинился. Что бы ты ему ответил?"]
    runtime = Runtime(db, corpus_path=corpus, timed=False)
    workers = [{"question": question, "reply": runtime.respond(question)} for question in controls + [
        "Привет, как дела?", "Что делаешь?", "Я наконец-то сдал экзамен", "Вроде нормально"]]
    timed = Runtime(db, corpus_path=corpus, timed=True, seed=42)
    schedule = [{"question": question, "reply": timed.respond(question)} for question in ("Привет, как дела?", controls[0])]
    report = {"label": "Known workbook routing regression, not holdout or human-likeness score",
              "code_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (ROOT / "arena" / "corpus.py", ROOT / "arena" / "engine.py", ROOT / "arena" / "runtime.py")},
              "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
              "routes": dict(Counter(row["reply"]["intent"] for row in rows)),
              "fallbacks": sum(row["reply"]["fallback"] for row in rows),
              "max_prepare_ms": max(row["prepare_ms"] for row in rows),
              "rows": rows, "real_workers": workers, "real_timed_delivery": schedule}
    output = ROOT / "evaluations" / "corpus-v2" / "integration.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: report[key] for key in ("label", "routes", "fallbacks", "max_prepare_ms")}, ensure_ascii=False))
    print(json.dumps({"real_timed_delivery": [{"chars": len(row["reply"]["text"]),
        "seconds": round(row["reply"]["elapsed"], 3), "status": row["reply"]["status"]} for row in schedule]}, ensure_ascii=False))


if __name__ == "__main__":
    run()
