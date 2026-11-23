"""Build the offline dialogue SQLite from reviewed XLSX source files."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arena.corpus_import import build_corpus


def run(argv=None):
    parser = argparse.ArgumentParser(description="Подготовка локального корпуса из XLSX")
    parser.add_argument("sources", nargs="+", type=Path, help="XLSX или папки с XLSX")
    parser.add_argument("--output", type=Path, required=True, help="новый SQLite файл")
    parser.add_argument("--review", type=Path, help="явный журнал проверки с SHA256 исходников")
    args = parser.parse_args(argv)
    sources = []
    for source in args.sources:
        sources.extend(sorted(source.glob("*.xlsx")) if source.is_dir() else [source])
    try:
        result = build_corpus(sources, args.output, review_path=args.review)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    run()
