import argparse
import contextlib
import importlib
import io
import json
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def run(project, destination):
    sys.path.insert(0, str(project))
    engine = importlib.import_module("engine")
    main = importlib.import_module("main")
    db = project / "data" / "demo.sqlite3"
    results = []

    def record(name, passed, details):
        results.append({"name": name, "passed": bool(passed), "details": details})

    bot = engine.Bot(db)
    inputs = ["", " \n\t", "я" * 50000, "Что такое фырбуль?", "😀" * 5000,
              "Вычисли 2 ** 100000000.", "Посчитай 1 / 0.",
              "Вычисли __import__('os').system('echo SHOULD_NOT_RUN').",
              "'; DROP TABLE facts; --", "Меня зовут «; DROP TABLE facts; --»."]
    with sqlite3.connect(db) as con:
        before = con.execute("SELECT count(*) FROM facts").fetchone()[0]
    stress_rows = []
    for question in inputs:
        start = time.perf_counter()
        try:
            reply = bot.answer(question)
            elapsed = time.perf_counter() - start
            valid = isinstance(reply.get("text"), str) and 1 <= len(reply["text"]) <= 300
            stress_rows.append({"input_chars": len(question), "answer": reply["text"],
                                "seconds": elapsed, "passed": valid and elapsed < 3})
        except Exception as exc:
            stress_rows.append({"input_chars": len(question), "error": str(exc), "passed": False})
    with sqlite3.connect(db) as con:
        after = con.execute("SELECT count(*) FROM facts").fetchone()[0]
    record("bounded_edge_inputs", all(r["passed"] for r in stress_rows), stress_rows)
    record("database_survived_text_inputs", before == after, {"before": before, "after": after})

    with tempfile.TemporaryDirectory(prefix="turing-spike-") as tmp:
        alternate = Path(tmp) / "alternate.sqlite3"
        with sqlite3.connect(db) as source, sqlite3.connect(alternate) as target:
            source.backup(target)
            target.execute("UPDATE facts SET object='Лера' WHERE id='name'")
            target.execute("UPDATE facts SET value=-3 WHERE object='tea' AND predicate='likes'")
            target.execute("UPDATE facts SET value=3 WHERE object='coffee' AND predicate='likes'")
            target.commit()
        source.close()
        target.close()
        swapped = engine.Bot(alternate)
        name_reply = swapped.answer("Как тебя зовут?")
        choice_reply = swapped.answer("Чай или кофе?")
        record("alternate_database_changes_behavior",
               "Лера" in name_reply["text"] and "кофе" in choice_reply["text"].lower(),
               {"name": name_reply, "choice": choice_reply})
        swapped.db.close()

    pending = engine.Bot(db)
    candidate = pending.prepare("Меня зовут Марина.")
    before_commit = pending.prepare("Как меня зовут?")
    pending.commit("Меня зовут Марина.", candidate)
    after_commit = pending.prepare("Как меня зовут?")
    record("user_fact_committed_only_after_delivery",
           "Марина" not in before_commit["text"] and "Марина" in after_commit["text"],
           {"before_commit": before_commit, "after_commit": after_commit})

    class FixedRandom:
        def __init__(self, seed):
            pass

        def uniform(self, low, high):
            return high

    timing_rows = []
    for length, processing in ((1, 0.2), (50, 1), (300, 2), (300, 12)):
        class FakeBot:
            def __init__(self, path):
                pass

            def prepare(self, question):
                return {"text": "я" * length}

            def commit(self, question, result):
                pass

        with patch.object(sys, "argv", ["main.py", "--ask", "test", "--timed"]), \
                patch.object(main, "Bot", FakeBot), \
                patch.object(main.time, "monotonic", side_effect=[0, processing]), \
                patch.object(main.time, "sleep") as sleeper, \
                patch.object(main.random, "Random", FixedRandom), \
                contextlib.redirect_stdout(io.StringIO()):
            main.run()
        delay = sleeper.call_args.args[0]
        total = processing + delay
        timing_rows.append({"length": length, "processing": processing, "wait": delay,
                            "total": total, "passed": 3 <= total <= 40})
    record("scheduled_time_includes_processing", all(r["passed"] for r in timing_rows), timing_rows)

    timed_rows = []
    for question in ("2 + 2", "Почему ты любишь чай?"):
        start = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(project / "main.py"), "--ask", question,
             "--timed", "--seed", "42"],
            cwd=project, capture_output=True, text=True, encoding="utf-8", timeout=44,
        )
        elapsed = time.monotonic() - start
        answer = completed.stdout.strip()
        expected = max(3, min(40, 3 + 0.12 * len(answer) + random.Random(42).uniform(-1, 1)))
        valid = completed.returncode == 0 and bool(answer) and expected <= elapsed <= expected + 2
        timed_rows.append({"question": question, "answer": answer,
                           "seconds": round(elapsed, 3), "expected": round(expected, 3), "passed": valid})
    record("real_cli_length_dependent_delay", all(r["passed"] for r in timed_rows), timed_rows)
    payload = {"checks": results, "passed": sum(r["passed"] for r in results), "total": len(results)}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.project.resolve(), args.output.resolve())
