"""Export only traceable paraphrases reproduced by the running reply pipeline."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.corpus import Corpus
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import initial_state
from arena.paraphrases import equivalent
from arena.geography import geography_reply


GEOGRAPHY = {
    '21': ['А Алматы столица Казахстана', 'Алматы столица', 'Казахстанский столица это Алматы же',
           'Столицей Казахстана считается Алматы?', 'Алма-Ата же столица РК?',
           'А Казахстана столица Алматы же', 'Алматы является столицей Казахстана?',
           'Столица Казахстана это Алматы', 'Казахстанская столица Алматы?',
           'Алматы столица РК что ли', 'Алматы правда столица Казахстана?',
           'Столица Казахстана Алматы или как'],
    '22': ['А Стамбул столица Турции', 'Турецкая столица это Стамбул?',
           'Стамбул является столицей Турции?', 'Столицей Турции считается Стамбул',
           'Турции столица Стамбул же', 'Стамбул столица?', 'Столица Турции это Стамбул'],
    '23': ['Море это Байкал или как', 'Байкал является морем?', 'Байкал море или озеро',
           'Озеро или море Байкал?', 'Байкал считается морем?', 'Это море Байкал?',
           'Байкал же озеро', 'Байкал это озеро или море?'],
    '25': ['На севере Антарктида?', 'Антарктида находится на севере',
           'Антарктида расположена в северном полушарии?', 'Северное полушарие это Антарктида?',
           'В южном полушарии Антарктида?', 'Антарктида на юге?', 'Антарктида на севере или юге'],
    'geo-taiwan-independent': ['Тайвань независимая страна', 'Независимая страна это Тайвань?',
           'Тайвань является самостоятельным государством', 'Тайвань отдельная страна?',
           'Тайвань независимое государство?', 'Независимым государством является Тайвань?',
           'Тайвань суверенное государство?', 'Страна Тайвань независимая?'],
    'geo-taiwan-status': ['Тайвань часть Китая?', 'Тайвань принадлежит Китаю?', 'Какой статус у Тайваня?',
           'Тайвань страна или часть Китая'],
    'geo-taiwan-island': ['Тайвань город Китая?', 'Китайским городом является Тайвань?',
           'Город Китая это Тайвань?', 'Тайвань это китайский город?',
           'Тайвань считается городом Китая?', 'Город или остров Тайвань?'],
}


def history_for(turns):
    history = []
    pending = None
    for turn in turns or []:
        if turn['role'] == 'user':
            if pending is not None:
                history.append({'question': pending, 'text': ''})
            pending = turn['text']
        else:
            history.append({'question': pending or '', 'text': turn['text']})
            pending = None
    if pending is not None:
        history.append({'question': pending, 'text': ''})
    return history


def clean_reply(text):
    return ' '.join(text.replace('—', ' ').replace('–', ' ').replace('--', ' ').split()).rstrip(' .')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'local/paraphrases',
                        help='directory containing candidate_variants.json and receiving verification reports')
    parser.add_argument('--corpus', type=Path, default=ROOT / 'data/dialogue-combined-5350-v2.sqlite3')
    parser.add_argument('--export', type=Path,
                        help='grouped JSON export; defaults to Turing-Arena-v3-варианты.json in --directory')
    parser.add_argument('--overwrite', action='store_true', help='replace existing verification outputs')
    args = parser.parse_args()
    candidates_path = args.directory / 'candidate_variants.json'
    export_path = args.export or args.directory / 'Turing-Arena-v3-варианты.json'
    output_paths = [args.directory / name for name in (
        'accepted_variants.json', 'rejected_variants.json', 'grouped_variants.json', 'verification.json')]
    resolved_outputs = [path.resolve() for path in [*output_paths, export_path]]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        parser.error('--export must not replace one of the verification reports')
    if any(path in {args.corpus.resolve(), candidates_path.resolve()} for path in resolved_outputs):
        parser.error('Output paths must not overwrite the corpus or input candidates')
    if not candidates_path.is_file():
        parser.error('Generate candidate_variants.json first, or select its directory with --directory')
    if not args.overwrite and any(path.exists() for path in [*output_paths, export_path]):
        parser.error('Verification outputs already exist; choose a new directory or pass --overwrite')
    corpus = Corpus(args.corpus)
    lexicon = ensure_demo_database()
    sources = {row['example_id']: row for row in corpus.rows if row['kind'] == 'reply'}
    candidates = json.loads(candidates_path.read_text(encoding='utf-8'))
    accepted, rejected = [], []
    # Use the actual generator; cache just the immutable corpus instance to avoid
    # rebuilding 6,000 rows for every test. Spawned worker checks run separately.
    with patch('arena.corpus.Corpus', return_value=corpus):
        for candidate in candidates:
            source = sources.get(candidate['example_id'])
            reason = None
            if source is None or source['prompt'] != candidate['source_prompt'] or source['answer'] != candidate['answer'] or source['context'] != candidate['context']:
                reason = 'source_changed'
            elif not equivalent(source['prompt'], candidate['prompt']):
                reason = 'unsupported_equivalence'
            else:
                state = initial_state()
                state['history'] = history_for(source['context_turns'])
                state['last_topic'] = 'corpus:' + source['topic'] if state['history'] else None
                reply = generate(candidate['prompt'], state, lexicon, corpus_path=args.corpus)
                if reply['fallback'] or reply['text'] != clean_reply(source['answer']):
                    reason = 'different_runtime_reply'
            if reason:
                rejected.append({**candidate, 'reason': reason})
            else:
                accepted.append({**candidate, 'answer': clean_reply(source['answer']), 'context_turns': source['context_turns']})
    grouped = {}
    source_groups = {}
    for source in sources.values():
        identifier = source['example_id']
        # The authored 5,000 examples have five phrasings per scenario.
        group_id = ('scenario-' + str((int(identifier) - 351) // 5 + 1)
                    if identifier.isdigit() and int(identifier) >= 351 else 'original-' + identifier)
        if group_id in grouped and (grouped[group_id]['answer'] != clean_reply(source['answer']) or grouped[group_id]['context'] != source['context']):
            group_id += '-alternative'
        group = grouped.setdefault(group_id, {'group_id': group_id, 'source_ids': [], 'topic': source['topic'],
            'context': source['context'], 'original_prompts': [], 'new_variants': [], 'answer': clean_reply(source['answer'])})
        if group['answer'] != clean_reply(source['answer']) or group['context'] != source['context']:
            raise ValueError('Inconsistent scenario: ' + group_id)
        group['source_ids'].append(identifier)
        group['original_prompts'].append(source['prompt'])
        source_groups[identifier] = group_id
    for candidate in accepted:
        identifier = candidate['example_id']
        group_id = source_groups[identifier]
        grouped[group_id]['new_variants'].append(candidate['prompt'])
    old_prompts = {re.sub(r'[^\w]+', ' ', row['prompt'].casefold().replace('ё', 'е')).strip() for row in sources.values()}
    for identifier, prompts in GEOGRAPHY.items():
        for prompt in prompts:
            relation = geography_reply(prompt)
            if relation is None:
                raise ValueError('Unsupported geographic variant: ' + prompt)
            expected = relation['text']
            reply = generate(prompt, initial_state(), lexicon, corpus_path=args.corpus)
            if reply['fallback'] or reply['text'] != expected:
                raise ValueError('Geographic runtime mismatch: ' + prompt)
            if re.sub(r'[^\w]+', ' ', prompt.casefold().replace('ё', 'е')).strip() in old_prompts:
                continue
            source = sources.get(identifier)
            group_id = source_groups.get(identifier, identifier)
            group = grouped.setdefault(group_id, {'group_id': group_id, 'source_ids': [], 'topic': 'География',
                'context': '', 'original_prompts': [], 'new_variants': [], 'answer': expected})
            if group['answer'] != expected:
                raise ValueError('Geographic answers must stay separate: ' + prompt)
            group['new_variants'].append(prompt)
            accepted.append({'example_id': identifier, 'prompt': prompt, 'source_prompt': source['prompt'] if source else '',
                'answer': expected, 'context': '', 'context_turns': [], 'transformation': 'geographic_relation'})
    report = {'candidate_count': len(candidates), 'accepted_new_variants': len(accepted),
              'covered_source_rows': len({row['example_id'] for row in accepted}),
              'active_original_rows': len(sources), 'groups': len(grouped),
              'rejections': dict(Counter(row['reason'] for row in rejected)),
              'transformation_counts': dict(Counter(row['transformation'] for row in accepted))}
    for name, data in [('accepted_variants.json', accepted), ('rejected_variants.json', rejected),
                       ('grouped_variants.json', list(grouped.values())), ('verification.json', report)]:
        (args.directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(list(grouped.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
