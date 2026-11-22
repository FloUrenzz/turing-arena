import argparse
import hashlib
import importlib
import json
import socket
import sys
import time
from pathlib import Path


def run(project, output, cases_path):
    network_attempts = []

    def deny_network(*args, **kwargs):
        network_attempts.append("attempt")
        raise RuntimeError("Network use is forbidden during this evaluation")

    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    sys.path.insert(0, str(project))
    engine = importlib.import_module("engine")
    db = project / "data" / "demo.sqlite3"
    fixture_bytes = cases_path.read_bytes()
    fixtures = json.loads(fixture_bytes)
    results = []

    def check(bot, item, group):
        start = time.perf_counter()
        error = None
        try:
            reply = bot.answer(item["question"])
        except Exception as exc:
            reply = {}
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - start) * 1000
        text = reply.get("text", "")
        failures = []
        if error:
            failures.append(error)
        if not isinstance(text, str) or not text.strip():
            failures.append("empty or non-text answer")
            text = ""
        if len(text) > 300:
            failures.append("more than 300 characters")
        if elapsed_ms > 3000:
            failures.append("preparation exceeded 3 seconds")
        if not isinstance(reply.get("intent"), str):
            failures.append("missing intent in diagnostic reply")
        if item.get("contains_any") and not any(
            token.casefold() in text.casefold() for token in item["contains_any"]
        ):
            failures.append("expected content not found")
        for token in item.get("excludes", []):
            if token.casefold() in text.casefold():
                failures.append("contradictory content: " + token)
        if "fallback" in item and reply.get("fallback") != item["fallback"]:
            failures.append(f"expected fallback={item['fallback']}")
        if item.get("intents") and reply.get("intent") not in item["intents"]:
            failures.append("unexpected semantic action")
        record = {
            "id": item["id"], "group": group, "question": item["question"],
            "answer": text, "intent": reply.get("intent"),
            "fallback": reply.get("fallback"), "concepts": reply.get("concepts"),
            "facts": reply.get("facts"), "elapsed_ms": round(elapsed_ms, 4),
            "passed": not failures, "failures": failures,
        }
        results.append(record)
        return record

    for group in ("known", "unknown", "challenge"):
        for item in fixtures[group]:
            check(engine.Bot(db), item, group)
    conversations = []
    for conversation in fixtures["conversations"]:
        bot = engine.Bot(db)
        turns = [check(bot, item, "conversation") for item in conversation["turns"]]
        conversations.append({"id": conversation["id"], "passed": all(t["passed"] for t in turns)})

    load_bot = engine.Bot(db)
    load_questions = [
        "Ты любишь чай?", "А почему?", "Как тебя зовут?", "Сколько будет 17 + 26?",
        "Что такое бжумп?", "А кофе?", "Чай или кофе?", "Ты любишь музыку?",
    ]
    load_start = time.perf_counter()
    load_max_ms = 0.0
    load_errors = []
    for index in range(1000):
        question = load_questions[index % len(load_questions)]
        started = time.perf_counter()
        try:
            reply = load_bot.answer(question)
            text = reply["text"]
            if not isinstance(text, str) or not 1 <= len(text) <= 300:
                load_errors.append({"index": index, "error": "invalid answer length"})
        except Exception as exc:
            load_errors.append({"index": index, "error": f"{type(exc).__name__}: {exc}"})
        load_max_ms = max(load_max_ms, (time.perf_counter() - started) * 1000)
    load_seconds = time.perf_counter() - load_start

    summaries = {}
    for group in ("known", "unknown", "challenge", "conversation"):
        group_results = [r for r in results if r["group"] == group]
        summaries[group] = {"passed": sum(r["passed"] for r in group_results), "total": len(group_results)}
    summaries["complete_conversations"] = {
        "passed": sum(r["passed"] for r in conversations), "total": len(conversations),
    }
    report = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "summary": summaries,
        "spike_acceptance": {
            "known_at_least_20_of_25": summaries["known"]["passed"] >= 20,
            "unknown_at_least_9_of_10": summaries["unknown"]["passed"] >= 9,
        },
        "network_guard": {"method": "socket calls rejected before engine import", "attempts": len(network_attempts)},
        "load": {
            "count": 1000, "seconds": round(load_seconds, 4),
            "max_answer_ms": round(load_max_ms, 4), "errors": load_errors,
        },
        "max_case_ms": round(max(r["elapsed_ms"] for r in results), 4),
        "results": results, "conversations": conversations,
        "limitations": [
            "Automated content/intent checks are not an assessment of human likeness.",
            "Blocking socket calls is not a physical offline-device demonstration.",
            "The engine author was not given these questions during initial implementation.",
            "Known preferences and expected behavior were defined for this demo persona.",
            "Challenge cases intentionally probe capabilities beyond the small prototype.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "fixture_sha256", "summary", "spike_acceptance", "network_guard", "load", "max_case_ms"
    )}, ensure_ascii=False, indent=2))
    print("Failing cases:")
    for result in results:
        if not result["passed"]:
            print(f"{result['id']}: {result['question']} -> {result['answer']} [{'; '.join(result['failures'])}]")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    args = parser.parse_args()
    run(args.project.resolve(), args.output.resolve(), args.cases.resolve())
