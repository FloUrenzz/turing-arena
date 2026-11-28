"""Build the optional offline corpus for explanatory, advice and dialogue questions."""

import argparse
from collections import defaultdict
from contextlib import closing
from itertools import islice, product
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena.expansion_corpus import EXPANSION_NAME, JURY_NAME, lookup_key, utterance_key
from arena.expansion_keywords import build_keyword_index
from scripts.build_expansion import (
    PACKS, QUESTION_OPENERS, SCHEMA, clean_pair, lower_first, previous_keys, topic_rows,
    variants, with_tail,
)


FAMILIES = {
    'explanations': 'Объяснения для жюри',
    'advice': 'Советы для жюри',
    'social': 'Диалоги для жюри',
}
ROWS_PER_FAMILY = 1_000_000
_REQUESTS = ('Ответь', 'Можешь ответить', 'Объясни', 'Можешь объяснить',
             'Расскажи', 'Можешь рассказать', 'Подскажи')
_WORDINGS = (
    'коротко', 'попроще', 'обычными словами', 'своими словами', 'без сложных слов',
    'без лишних деталей', 'в двух словах', 'по-простому', 'по делу', 'если знаешь',
    'буквально в паре фраз', 'как в переписке', 'коротко и понятно', 'в общих чертах',
    'без заумных слов', 'в паре предложений', 'как другу', 'пожалуйста',
)


def jury_variants(prompt):
    for variant in variants(prompt):
        if len(variant) <= 220:
            yield variant
    first_word = prompt.casefold().split(maxsplit=1)[0].rstrip(',:')
    for opener in ('', *QUESTION_OPENERS):
        if opener and opener.casefold().split(maxsplit=1)[0].rstrip(',:') == first_word:
            continue
        question = opener + lower_first(prompt) if opener else prompt
        for wording, request in product(_WORDINGS, _REQUESTS):
            punctuation = '?' if request.startswith('Можешь') else ''
            variant = with_tail(question, f' {request} {wording}{punctuation}')
            if len(variant) <= 220:
                yield variant


def collect_scenarios():
    seen = previous_keys()
    extension = ROOT / 'data' / EXPANSION_NAME
    if extension.is_file():
        with closing(sqlite3.connect(extension.as_uri() + '?mode=ro', uri=True)) as db:
            seen.update(key for (key,) in db.execute('SELECT lookup FROM utterances'))
    scenarios = []
    groups = defaultdict(list)
    for pack, family in FAMILIES.items():
        sample_pairs = runpy.run_path(str(PACKS / f'jury_{pack}.py'))['SCENARIOS']
        for topic, prompt, answer in sample_pairs:
            if topic != family:
                raise ValueError(f'Unexpected family in {pack}: {topic}')
            prompt = ' '.join(prompt.split())
            answer = ' '.join(answer.split())
            clean_pair(prompt, answer)
            key = lookup_key(utterance_key(prompt))
            if key not in seen:
                seen.add(key)
                scenarios.append((topic, prompt, answer))
                groups[topic].append(len(scenarios))
    if set(groups) != set(FAMILIES.values()):
        raise ValueError('Each family must contribute at least one new scenario')
    return scenarios, groups, seen


def build(output, quota):
    scenarios, groups, seen = collect_scenarios()
    if quota < max(map(len, groups.values())):
        raise ValueError('The quota must be at least as large as each base scenario group')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.sqlite3.tmp', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute('PRAGMA foreign_keys = ON')
            db.execute('PRAGMA cache_size = -96000')
            db.executescript(SCHEMA)
            db.executemany('INSERT INTO scenarios(topic,prompt,answer) VALUES (?,?,?)', scenarios)
            for family_number, (family, identifiers) in enumerate(groups.items()):
                source = topic_rows(scenarios, identifiers, seen, quota, variant_factory=jury_variants)
                rows = ((key, number, identifier) for number, (identifier, key, _)
                        in enumerate(source, start=family_number * quota + 1))
                for batch in iter(lambda: list(islice(rows, 50_000)), []):
                    db.executemany('INSERT INTO utterances(lookup,id,scenario_id) VALUES (?,?,?)', sorted(batch))
                print(f'{family}: {quota:,} forms, {len(identifiers):,} base prompts', flush=True)
            documents, terms = build_keyword_index(db)
            db.commit()
            db.execute('VACUUM')
            expected = quota * len(groups)
            if (db.execute('PRAGMA quick_check').fetchone() != ('ok',) or
                    db.execute('SELECT COUNT(*) FROM utterances').fetchone() != (expected,)):
                raise ValueError('Invalid generated jury corpus')
        temporary.rename(output)
        print(f'{output}: {expected:,} lookup keys; {documents:,} indexed prompts; {terms:,} terms')
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / JURY_NAME)
    parser.add_argument('--per-family', type=int, default=ROWS_PER_FAMILY,
                        help='number of distinct phrasings per family')
    args = parser.parse_args()
    if args.per_family <= 0:
        parser.error('--per-family must be positive')
    if args.output.exists():
        parser.error(f'Choose a new output path: {args.output}')
    build(args.output, args.per_family)


if __name__ == '__main__':
    main()
