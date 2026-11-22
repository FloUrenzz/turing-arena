import argparse
import json
from pathlib import Path
import sys

from arena.runtime import Runtime


def run(argv=None):
    parser = argparse.ArgumentParser(description="Локальный алгоритмический бот")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ask", help="один вопрос")
    mode.add_argument("--chat", action="store_true", help="диалог")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--fast", action="store_true", help="только разработка: без искусственной задержки")
    parser.add_argument("--json", action="store_true", help="диагностика вместо сценического текста")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    if args.db is None:
        from arena.data import ensure_demo_database
        db_path = ensure_demo_database()
    else:
        db_path = args.db
        if not db_path.is_file():
            parser.error("Указанная локальная БД не найдена; она не будет пересоздана автоматически")
    runtime = Runtime(db_path, timed=not args.fast, seed=args.seed)
    if args.fast or args.json:
        print("Исследовательский режим; для сценического вывода запускайте без --fast/--json.", file=sys.stderr)

    def deliver(reply):
        print(json.dumps(reply, ensure_ascii=False) if args.json else reply["text"], flush=True)
        print(f"Время до выдачи: {reply['elapsed']:.3f} с; символов: {len(reply['text'])}; статус: {reply['status']}", file=sys.stderr, flush=True)

    while True:
        try:
            if args.chat:
                print("Вопрос: ", end="", file=sys.stderr, flush=True)
                question = input()
            else:
                question = args.ask
            runtime.respond(question, sink=deliver)
        except (EOFError, KeyboardInterrupt):
            break
        if not args.chat:
            break


if __name__ == "__main__":
    run()
