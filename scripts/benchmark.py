import argparse
import json
from pathlib import Path
import socket
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import apply_reply, initial_state


def run(count):
    db = ensure_demo_database()
    questions = ["Почему появляется радуга?", "А без солнца?", "Чай или кофе?",
                 "Друг опоздал и не извинился. Что сказать?", "Я опоздал. Что написать другу?",
                 "Еду в Астану зимой. Что взять?", "Что посоветуешь для Астаны летом?",
                 "Меня зовут Дина.", "Как меня зовут?", "Сколько будет (17+26)*3?",
                 "Переверни слово «самолёт».", "Что такое флюмп?"]
    state = initial_state()
    timings, errors = [], []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")):
        for index in range(count):
            question = questions[index % len(questions)]
            started = time.perf_counter()
            try:
                result = generate(question, state, db)
                assert result["text"].strip() and len(result["text"]) <= 300
                assert len(result["text"].encode("utf-16-le")) // 2 <= 300
                state = apply_reply(state, question, result)
            except Exception as error:
                errors.append({"index": index, "error": type(error).__name__})
            timings.append((time.perf_counter() - started) * 1000)
    ordered = sorted(timings)
    report = {"count": count, "errors": errors, "history_size": len(state["history"]),
              "p50_prepare_ms": round(statistics.median(timings), 3),
              "p95_prepare_ms": round(ordered[int((count - 1) * .95)], 3),
              "max_prepare_ms": round(max(timings), 3),
              "note": "Прямой движок без искусственной задержки и spawn; не оценка человечности."}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.count <= 100000:
        parser.error("count должен быть от 1 до 100000")
    raise SystemExit(run(args.count))
