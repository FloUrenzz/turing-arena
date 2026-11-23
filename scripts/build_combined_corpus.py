"""Combine the existing review with the explicitly enabled 5000-row workbook."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.corpus_import import _records, build_corpus
from arena.corpus import STOP, key, literal_signature, signature, tokens


def equivalence(text):
    words = [word for word in tokens(text) if word not in STOP]
    person, addressee, numbers, when, negative, question, act = signature(text)
    return (tuple(words) if len(words) >= 2 else (key(text),), person, addressee,
            numbers, tuple(sorted(when)), tuple(sorted(negative)), question, act,
            literal_signature(text))


def harmonize_new_replies(review, records, old_ids):
    """Keep context starters consistent with an existing standalone answer."""
    decisions = {item['example_id']: item for item in review['decisions']}
    standalone = {}
    changes = 0
    for record in sorted(records, key=lambda row: int(row[3])):
        item = decisions[record[3]]
        if record[5] or item['decision'] == 'hold':
            continue
        answer = item.get('answer', record[7])
        canonical = standalone.setdefault(equivalence(record[6]), answer)
        if answer != canonical and record[3] not in old_ids:
            item.update(decision='rewrite', answer=canonical,
                        reason='Ответ согласован с эквивалентной уже подключённой формулировкой')
            changes += 1
    for item in review['decisions']:
        if item['example_id'] in old_ids:
            continue
        turns = item.get('context_turns', [])
        for user, bot in zip(turns, turns[1:]):
            if user['role'] != 'user' or bot['role'] != 'bot':
                continue
            canonical = standalone.get(equivalence(user['text']))
            if canonical and canonical != bot['text']:
                bot['text'] = canonical
                item['reason'] = 'Предыдущий ответ согласован с самостоятельной репликой общей базы; итоговый ответ сохранён'
                changes += 1
    return changes


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('workbook', type=Path, nargs='?',
                        default=ROOT / 'datasets/source-extra/Turing-Arena-ещё-5000-реплик.xlsx',
                        help='5000-row source workbook; defaults to the copy included in the repository')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review-output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.review_output.exists():
        parser.error('Choose new output paths; existing files are preserved')
    if not args.workbook.is_file():
        parser.error('The source workbook does not exist: ' + str(args.workbook))
    review = json.loads((ROOT / 'data/corpus_review.json').read_text(encoding='utf-8'))
    old_ids = {item['example_id'] for item in review['decisions']}
    sources = [ROOT / 'datasets' / filename for filename in review['sources']]
    old_records = [record for source in sources
                   for _, batch in _records(source, review['sources'][source.name]) for record in batch]
    checksum = hashlib.sha256(args.workbook.read_bytes()).hexdigest()
    new_records = [record for _, records in _records(args.workbook, checksum) for record in records]
    if len(new_records) != 5000:
        parser.error('Expected the 5000-row reviewed workbook')
    review['sources'][args.workbook.name] = checksum
    review['reviewer'] = 'Codex AI-assisted editorial review and user-authorized combined activation'
    review['authorization'] += (
        ' 2026-11-23: пользователь после получения Excel на проверку явно попросил '
        '«запусти заново с общими строками». Подключены 5000 новых строк к прежнему '
        'корпусу; исходные решения по 350 прежним примерам сохранены.'
    )
    for record in new_records:
        example_id, context, answer = record[3], record[5], record[7]
        if example_id in old_ids:
            raise ValueError('Repeated example id: ' + example_id)
        item = {'example_id': example_id, 'decision': 'accept',
                'reason': 'Пара проверена при подготовке 5000 реплик; пользователь разрешил общий запуск'}
        if context:
            user, delimiter, bot = context.partition('\nБот: ')
            if not user.startswith('Собеседник: ') or not delimiter or not bot:
                raise ValueError('Unexpected context at example ' + example_id)
            item.update(decision='rewrite', answer=answer,
                        context_turns=[{'role': 'user', 'text': user.removeprefix('Собеседник: ')},
                                       {'role': 'bot', 'text': bot}],
                        reason='Ответ сохранён; предыдущие реплики размечены по собеседникам для проверки контекста')
        review['decisions'].append(item)
    harmonized = harmonize_new_replies(review, [*old_records, *new_records], old_ids)
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = build_corpus([*sources, args.workbook], args.output, review_path=args.review_output)
    counts['harmonized_decisions'] = harmonized
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == '__main__':
    run()
