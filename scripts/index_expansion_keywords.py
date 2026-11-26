"""Add or refresh the keyword index in an existing expansion SQLite file."""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.expansion_corpus import EXPANSION_NAME
from arena.expansion_keywords import build_keyword_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data' / EXPANSION_NAME)
    args = parser.parse_args()
    with closing(sqlite3.connect(args.database.resolve().as_uri() + '?mode=rw', uri=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            scenarios, terms = build_keyword_index(db)
    print(f'Сценариев в индексе {scenarios}, ключевых слов {terms}')


if __name__ == '__main__':
    main()
