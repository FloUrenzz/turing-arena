"""Build distinct Russian question/answer pairs with a quota per topic."""

import argparse
from collections import defaultdict
from contextlib import closing
import csv
import io
from itertools import product
import json
from pathlib import Path
import re
import runpy
import sqlite3
import sys
import tempfile
import unicodedata
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.expansion_corpus import BASE_NAME, EXPANSION_NAME, lookup_key, utterance_key
from arena.expansion_keywords import build_keyword_index


PACKS = ROOT / 'datasets/source-extra'
ROWS_PER_TOPIC = 100_000
HEADERS = ('№', 'Тема', 'Что пишут', 'Ответ бота', 'Ситуация')
SCHEMA = '''
PRAGMA user_version = 1;
CREATE TABLE scenarios(id INTEGER PRIMARY KEY, topic TEXT NOT NULL,
                       prompt TEXT NOT NULL, answer TEXT NOT NULL);
CREATE TABLE utterances(lookup BLOB PRIMARY KEY, id INTEGER NOT NULL,
                        scenario_id INTEGER NOT NULL REFERENCES scenarios(id)) WITHOUT ROWID;
'''
PROFANITY = re.compile(r'\b(?:бля(?:дь|ть)?|сука|пизд\w*|хуй\w*|хуе\w*|хуя\w*|еба\w*|заеб\w*|нахуй|похуй|охуе\w*|ебан\w*|мудак\w*)\b', re.I)
FIRST_PERSON = re.compile(r'^(?:хочу|решил[а]?|собираюсь|планирую|заметил[а]?|забыл[а]?|потерял[а]?|купил[а]?|начал[а]?|записал[а]?|думаю|пытаюсь|ищу|не (?:знаю|могу|понимаю|успеваю)|договорил(?:ся|ась))\b', re.I)
EDIT_OPENINGS = (
    (r'^что делать, если ', ('Как быть, если ', 'Что можно сделать, если ')),
    (r'^как быть, если ', ('Что делать, если ', 'Что можно сделать, если ')),
    (r'^как лучше ', ('Как можно ', 'Подскажи, как лучше ')),
    (r'^не получается ', ('Никак не могу ', 'У меня не выходит ')),
    (r'^я не могу ', ('Никак не могу ', 'У меня не получается ')),
    (r'^не знаю, как ', ('Не могу понять, как ', 'Пока не знаю, как ')),
    (r'^не знаю, что ', ('Не могу понять, что ', 'Пока не знаю, что ')),
    (r'^хочу ', ('Мне хочется ', 'Хотелось бы ')),
    (r'^собираюсь ', ('Планирую ', 'Думаю ')),
    (r'^планирую ', ('Собираюсь ', 'Думаю ')),
    (r'^у меня ', ('У меня тут ',)),
    (r'^подскажи, ', ('Скажи, ', 'Можешь подсказать, ')),
    (r'^каждый раз ', ('Постоянно ',)),
    (r'^первый раз ', ('Впервые ',)),
    (r'^осталось доделать ', ('Надо только доделать ',)),
    (r'^как проще ', ('Как попроще ',)),
    (r'^хочу попробовать ', ('Думаю попробовать ', 'Хотелось бы попробовать ')),
)
COLLOQUIAL = (
    (r'\bчтобы\b', 'чтоб'), (r'\bсейчас\b', 'щас'), (r'\bчто делать\b', 'чё делать'),
    (r'\bдомашнее задание\b', 'домашку'), (r'\bпрезентацию\b', 'презу'),
    (r'\bв первый раз\b', 'впервые'), (r'\bдо сих пор\b', 'всё ещё'),
)
QUESTION_OPENERS = ('Слушай, ', 'Кстати, ', 'А ', 'Смотри, ', 'Скажи, ',
                    'А вот ', 'Мне интересно, ', 'Можно спросить: ', 'Слушай, можно спросить: ',
                    'Насчёт одного вопроса: ', 'К слову, ', 'Кстати, вопрос: ', 'Вот ещё что: ',
                    'Есть вопрос: ', 'Я тут хотел спросить: ', 'Слушай, ещё такой вопрос: ',
                    'Я вот подумал: ', 'Ещё спрошу: ', 'Пока вспомнил, ', 'Сейчас подумал: ',
                    'Подскажи, ', 'Знаешь, ', 'Скажи, пожалуйста, ', 'У меня вопрос: ',
                    'Кстати, можно спросить: ', 'Раз уж заговорили, ', 'Я тут подумал: ',
                    'Слушай, я спросить хотел: ', 'А тогда ', 'Просто интересно, ',
                    'Слушай, вопрос на минуту: ', 'Можно тебя спросить: ',
                    'Если не отвлекаю, ', 'На всякий случай спрошу: ', 'Ещё вопрос: ')
STATEMENT_OPENERS = ('Слушай, ', 'Кстати, ', 'Смотри, ', 'Короче, ', 'Ну вот, ',
                     'В общем, ', 'Слушай, тут такое: ', 'Короче говоря, ', 'Так вот, ',
                     'Вот что: ', 'К слову, ', 'Вот ещё что: ', 'Кстати, забыл сказать: ',
                     'Если что, ', 'Вот так: ', 'Я вот подумал: ', 'Кстати, тут такое: ',
                     'Пока вспомнил, ', 'Смотри, какая штука: ', 'Вот какая история: ',
                     'Слушай, расскажу: ', 'Ну, в общем, ', 'Кстати, ещё кое-что: ',
                     'Между делом скажу: ', 'Есть ещё момент: ', 'Слушай, хотел сказать: ',
                     'Пока помню, ', 'Тут вот что: ', 'У меня тут такое: ', 'Знаешь, ',
                     'О, вспомнил: ', 'Кстати, поделюсь: ', 'А ещё ', 'Если коротко, ',
                     'Слушай, кстати, ', 'Вот, вспомнил: ', 'Ладно, расскажу: ')
QUESTION_TAILS = (
    '', ' Подскажешь?', ' Как думаешь?', ' Что скажешь?', ' Есть мысли?',
    ' Просто хочу понять', ' Мне правда интересно', ' Может, знаешь?',
    ' Хочется разобраться', ' Можешь подсказать?', ' Интересно твоё мнение',
    ' И что думаешь?', ' Буду рад, если подскажешь', ' Есть идеи?',
    ' Что думаешь по этому поводу?', ' Если знаешь, скажи', ' Мне это интересно',
    ' Просто хочу спросить', ' Хотелось бы понять', ' Если можешь, подскажи',
    ' Хочу это понять', ' Просто не уверен', ' Ты что-нибудь про это знаешь?',
    ' Может, поможешь разобраться?', ' Я тут хочу разобраться', ' Просто любопытно',
    ' Как тебе вообще этот вопрос?', ' Есть что подсказать?', ' Пытаюсь разобраться',
    ' Может, уже думал об этом?', ' Вот такой вопрос', ' Хочу услышать твоё мнение',
    ' Я вот об этом задумался', ' Как бы ты ответил?', ' Чё думаешь?',
)
STATEMENT_TAILS = (
    '', ', если что', ', кстати', ', если честно', ' Вот так', ' Как-то так',
    ' Просто делюсь', ' В общем, такая история', ' Вот что у меня',
    ' Решил рассказать', ' Вот такие дела', ' Просто хотел сказать',
    ' Как-то вот так', ' Просто рассказываю', ' Такие дела', ' Вот и всё',
    ' Просто поделился', ' В общем, вот', ' Это я так, к слову',
    ' Вот такой момент', ' Это если коротко', ' Решил поделиться',
    ' Это я на всякий случай сказал', ' Пока вот так', ' Это я к слову',
    ' О таком тоже хотел сказать', ' Просто говорю как есть',
    ' Вот что хотел рассказать', ' Ну вот и всё', ' Так, просто делюсь',
    ' Ну как-то так', ' Если совсем коротко, то так', ' Вот такая штука',
    ' Было желание этим поделиться', ' Просто решил об этом сказать',
)


def lower_first(text):
    # A leading acronym keeps its capitalization.
    return text if len(text) < 2 or text[:2].isupper() and text[1].isalpha() else text[0].lower() + text[1:]


def with_tail(prompt, tail):
    if not tail or prompt.endswith('?') or tail.startswith(','):
        return prompt + tail
    return prompt + '.' + tail


def variants(prompt):
    """Generate conversational openings and bounded rewrites without dropping content words."""
    yield prompt
    alternatives = []
    for pattern, replacements in EDIT_OPENINGS:
        found = re.match(pattern, prompt, re.I)
        if found:
            alternatives.extend(replacement + prompt[found.end():] for replacement in replacements)
    if FIRST_PERSON.match(prompt):
        alternatives.append('Я ' + lower_first(prompt))
    elif FIRST_PERSON.match(prompt[2:]) and prompt[:2].casefold() == 'я ':
        alternatives.append(prompt[2].upper() + prompt[3:])
    condition = re.fullmatch(r'(?:что делать|как быть), если (.+)\?', prompt, re.I)
    if condition and '?' not in condition[1]:
        alternatives.append('Если ' + condition[1] + ', что делать?')
    for pattern, replacement in COLLOQUIAL:
        alternative = re.sub(pattern, replacement, prompt, count=1, flags=re.I)
        if alternative != prompt:
            alternatives.append(alternative)
    yield from alternatives
    openers = QUESTION_OPENERS if prompt.endswith('?') else STATEMENT_OPENERS
    tails = QUESTION_TAILS if prompt.endswith('?') else STATEMENT_TAILS
    for index, opener in enumerate(openers):
        yield opener + lower_first(prompt)
        if alternatives and index < 5:
            yield opener + lower_first(alternatives[index % len(alternatives)])
    for tail in tails[1:]:
        yield with_tail(prompt, tail)
    # The opening and closing vary independently. Rotate the combination order
    # so a quota uses every opening, rather than filling up on a few wrappers.
    bodies = (prompt, *alternatives)
    for offset, (tail_index, opener) in enumerate(product(range(1, len(tails)), openers)):
        tail = tails[1 + (tail_index + offset % len(openers) - 1) % (len(tails) - 1)]
        lead = opener.casefold().split(maxsplit=1)[0].rstrip(',:')
        body = bodies[(tail_index + offset) % len(bodies)]
        if lead == body.casefold().split(maxsplit=1)[0].rstrip(',:'):
            continue
        if lead in ('кстати', 'слушай', 'подскажи', 'скажи') and lead in tail.casefold().split():
            continue
        yield with_tail(opener + lower_first(body), tail)


def clean_pair(prompt, answer):
    if not (0 < len(prompt) <= 220 and 0 < len(answer) <= 150):
        raise ValueError((prompt, answer))
    if answer.endswith(('.', '!', '…')) or any(char in answer for char in ('—', '–', '--')):
        raise ValueError((prompt, answer))
    if any(unicodedata.category(c).startswith(('C', 'S')) for c in answer) or PROFANITY.search(answer):
        raise ValueError((prompt, answer))
    if not re.search('[а-яё]', answer, re.I) or '\n' in prompt:
        raise ValueError((prompt, answer))


def previous_keys():
    keys = set()
    base = ROOT / 'data' / BASE_NAME
    with closing(sqlite3.connect(base.as_uri() + '?mode=ro', uri=True)) as db:
        keys.update(utterance_key(row[0]) for row in db.execute('SELECT prompt FROM corpus_replies'))
    export = ROOT / 'exports/Turing-Arena-v3-варианты.json'
    if export.is_file():
        for group in json.loads(export.read_text(encoding='utf-8')):
            for field in ('original_prompts', 'new_variants'):
                keys.update(utterance_key(prompt) for prompt in group[field])
    return {lookup_key(key) for key in keys}


def collect_scenarios():
    seen = previous_keys()
    scenarios = []
    topics = defaultdict(list)
    for pack in ('daily', 'social', 'study'):
        for topic, prompt, answer in runpy.run_path(str(PACKS / f'expansion_{pack}.py'))['SCENARIOS']:
            prompt = ' '.join(prompt.split()).rstrip(' .!')
            answer = ' '.join(answer.split()).rstrip(' .!')
            clean_pair(prompt, answer)
            key = lookup_key(utterance_key(prompt))
            if key not in seen:
                scenarios.append((topic, prompt, answer))
                topics[topic].append(len(scenarios))
                seen.add(key)
    if len(topics) != 35:
        raise ValueError(f'Expected 35 topics, got {len(topics)}')
    return scenarios, topics, seen


def topic_rows(scenarios, identifiers, seen, quota, *, variant_factory=variants):
    for identifier in identifiers:
        prompt = scenarios[identifier - 1][1]
        yield identifier, lookup_key(utterance_key(prompt)), prompt
    remaining = quota - len(identifiers)
    generators = [(identifier, iter(variant_factory(scenarios[identifier - 1][1]))) for identifier in identifiers]
    while remaining and generators:
        advancing = []
        for identifier, generator in generators:
            for prompt in generator:
                key = lookup_key(utterance_key(prompt))
                if key in seen:
                    continue
                seen.add(key)
                yield identifier, key, prompt
                remaining -= 1
                advancing.append((identifier, generator))
                break
            if not remaining:
                return
        generators = advancing
    if remaining:
        raise ValueError(f'Need {remaining} more distinct phrasings for {scenarios[identifiers[0]-1][0]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / EXPANSION_NAME)
    parser.add_argument('--archive', type=Path, required=True, help='ZIP with one UTF-8 CSV per topic')
    parser.add_argument('--spreadsheet-input', type=Path, help='optional JSON preview with 100,000 balanced rows')
    args = parser.parse_args()
    for path in (args.output, args.archive, args.spreadsheet_input):
        if path is not None and path.exists():
            parser.error(f'Choose a new output path: {path}')
    scenarios, topics, seen = collect_scenarios()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix='.sqlite3', delete=False) as handle:
        db_temp = Path(handle.name)
    with tempfile.NamedTemporaryFile(dir=args.archive.parent, suffix='.zip', delete=False) as handle:
        archive_temp = Path(handle.name)
    try:
        preview = []
        total = 0
        counts = {}
        with closing(sqlite3.connect(db_temp)) as db, ZipFile(archive_temp, 'w', ZIP_DEFLATED, compresslevel=4) as archive:
            db.execute('PRAGMA foreign_keys = ON')
            db.execute('PRAGMA cache_size = -96000')
            db.executescript(SCHEMA)
            db.executemany('INSERT INTO scenarios(topic,prompt,answer) VALUES (?,?,?)', scenarios)
            for index, (topic, identifiers) in enumerate(topics.items(), 1):
                index_rows = []
                filename = f'{index:02d} {topic}.csv'
                preview_quota, preview_remainder = divmod(100_000, len(topics))
                with archive.open(filename, 'w') as raw:
                    with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as text:
                        writer = csv.writer(text, delimiter=';')
                        writer.writerow(HEADERS)
                        for row_number, (identifier, key, prompt) in enumerate(topic_rows(scenarios, identifiers, seen, ROWS_PER_TOPIC), 1):
                            total += 1
                            answer = scenarios[identifier - 1][2]
                            row = (total, topic, prompt, answer, identifier)
                            writer.writerow(row)
                            index_rows.append((key, total, identifier))
                            if args.spreadsheet_input and row_number <= preview_quota + (index <= preview_remainder):
                                preview.append(row)
                if len(index_rows) != ROWS_PER_TOPIC:
                    raise ValueError(f'Wrong row count for {topic}: {len(index_rows)}')
                db.executemany('INSERT INTO utterances(lookup,id,scenario_id) VALUES (?,?,?)', sorted(index_rows))
                counts[topic] = {'pairs': len(index_rows), 'bases': len(identifiers)}
                print(f'{index}/{len(topics)} {topic}: {len(index_rows)}', flush=True)
            archive.writestr('О наборе.txt', 'В каждой таблице 100 000 пар. Кодировка UTF-8 с BOM, разделитель точка с запятой.\nНомер ситуации связывает разные формулировки с общим ответом. Формулировки собраны автоматически по подготовленным сценариям.\n')
            build_keyword_index(db)
            db.commit()
            db.execute('VACUUM')
            if db.execute('PRAGMA quick_check').fetchone() != ('ok',) or total != len(topics) * ROWS_PER_TOPIC:
                raise ValueError('Invalid generated database')
        db_temp.rename(args.output)
        archive_temp.rename(args.archive)
    finally:
        db_temp.unlink(missing_ok=True)
        archive_temp.unlink(missing_ok=True)
    if args.spreadsheet_input is not None:
        args.spreadsheet_input.parent.mkdir(parents=True, exist_ok=True)
        args.spreadsheet_input.write_text(json.dumps(preview, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'rows': total, 'scenarios': len(scenarios), 'topics': counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()
