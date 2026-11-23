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
    corpus_mode = parser.add_mutually_exclusive_group()
    corpus_mode.add_argument("--corpus", type=Path, help="подготовленный SQLite-корпус реплик")
    corpus_mode.add_argument("--no-corpus", action="store_true", help="только смысловые правила, без корпуса")
    parser.add_argument("--fast", action="store_true", help="совместимость: ответы уже выдаются без искусственной задержки")
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
    corpus_path = None if args.no_corpus else args.corpus or Path(__file__).resolve().parent / "data" / "dialogue.sqlite3"
    if corpus_path is not None:
        if not corpus_path.is_file():
            if args.corpus:
                parser.error("Указанный корпус не найден. Сначала выполните scripts/import_corpus.py")
            corpus_path = None
        else:
            from arena.corpus import Corpus
            import sqlite3
            try:
                Corpus(corpus_path)
            except (ValueError, sqlite3.Error, KeyError) as error:
                parser.error("Невалидный корпус: " + str(error))
    runtime = Runtime(db_path, timed=False, seed=args.seed, corpus_path=corpus_path)

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
