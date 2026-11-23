"""Generate traceable phrasing candidates; do not activate or rewrite answers.

This is a bounded language transformation pass, not a random word shuffler.
Candidates are intentionally kept separate from the approved corpus. The caller
must verify them with the matcher before activation. Every candidate retains the
source example id, text, answer and context.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'local/paraphrases/candidate_variants.json'
LITERAL_MARKERS = ('«', '»', '"', '“', '”', '‘', '’', "'", '\n', '`')
FIRST_PERSON = set('''
хочу могу люблю думаю смотрю слушаю читаю пишу рисую ищу учусь отдыхаю скучаю
сижу жду иду еду пробую выбираю собираю делаю готовлю повторяю изучаю осваиваю
разбираю перебираю убираю проверяю вспоминаю пытаюсь планирую собираюсь
возвращаюсь просыпаюсь замечаю начинаю заканчиваю заканчиваюсь сравниваю
потерял потеряла нашёл нашел нашла подготовил подготовила закончил закончила
завершил завершила сделал сделала сдал сдала завалил завалила провалил провалила
забыл забыла купил купила прочитал прочитала посмотрел посмотрела скачал скачала
сохранил сохранила удалил удалила написал написала нарисовал нарисовала
собрал собрала приготовил приготовила разобрал разобрала починил починила
сломал сломала включил включила выключил выключила запустил запустила
открыл открыла закрыл закрыла устал устала проспал проспала опоздал опоздала
проснулся проснулась решил решила начал начала взял взяла выбрал выбрала
увидел увидела вышел вышла вернулся вернулась принёс принес принесла
оставил оставила забрал забрала перенёс перенес перенесла заметил заметила
успел успела забыл забыла попробовал попробовала отправил отправила
перепутал перепутала исправил исправила поставил поставила убрал убрала
разложил разложила получил получила нашёлся поменял поменяла достал достала
'''.split())
PRESENT_FIRST_PERSON = set('''
хочу могу люблю думаю смотрю слушаю читаю пишу рисую ищу учусь отдыхаю скучаю
сижу жду иду еду пробую выбираю собираю делаю готовлю повторяю изучаю осваиваю
разбираю перебираю убираю проверяю вспоминаю пытаюсь планирую собираюсь
возвращаюсь просыпаюсь замечаю начинаю заканчиваю сравниваю знаю понимаю помню
успеваю забываю замечаю обсуждаю показываю продолжаю сомневаюсь боюсь надеюсь
волнуюсь переживаю работаю гуляю играю учу слушаю ставлю лежу сплю жалею
путаюсь теряю нарезаю коллекционирую отвлекаюсь выбираюсь запускаю
'''.split())
FIRST_PERSON.update(PRESENT_FIRST_PERSON)
AMBIGUOUS_PAST = {'вышел', 'вышла', 'вернулся', 'вернулась', 'нашёлся', 'начал', 'начала'}
OBJECT_VERBS = set('''
потерял потеряла нашёл нашел нашла подготовил подготовила закончил закончила
завершил завершила сделал сделала сдал сдала завалил завалила провалил провалила
забыл забыла купил купила прочитал прочитала посмотрел посмотрела скачал скачала
сохранил сохранила удалил удалила написал написала нарисовал нарисовала
собрал собрала приготовил приготовила разобрал разобрала починил починила
сломал сломала включил включила выключил выключила запустил запустила
открыл открыла закрыл закрыла взял взяла выбрал выбрала увидел увидела
оставил оставила забрал забрала принёс принес принесла перенёс перенес перенесла
перепутал перепутала исправил исправила поставил поставила убрал убрала
смотрю слушаю читаю пишу рисую ищу собираю делаю готовлю повторяю изучаю
разбираю перебираю убираю проверяю вспоминаю сравниваю
'''.split())
SENSITIVE = set('''
сначала потом затем раньше позже потому поэтому вследствие вместо если когда
хотя но однако зато чтобы пока прежде больше меньше быстрее медленнее чем
между который которая которое которые и или а ли ведь пусть будто
он она они оно его её ее ему ей их им друг друзья подруга мама папа брат
сестра сосед коллега преподаватель учитель руководитель ты вы мы
'''.split())
PREPOSITIONS = set('в во на под над за перед после до от из с со к ко у о об для между возле через по без'.split())
TIME_WORDS = {'сегодня', 'завтра', 'вчера', 'сейчас', 'седня', 'щас', 'ща'}
LEXICAL = [
    ('сейчас', ('щас', 'ща', 'в данный момент'), 'colloquial_now'),
    ('сегодня', ('сёдня',), 'colloquial_today'),
    ('что', ('чё', 'чо'), 'colloquial_what'),
    ('вообще', ('ваще',), 'colloquial_generally'),
    ('нормально', ('норм', 'нормас'), 'colloquial_fine'),
    ('пожалуйста', ('плиз', 'пж'), 'colloquial_please'),
    ('почему', ('по какой причине',), 'reason_question'),
    ('зачем', ('для чего',), 'purpose_question'),
    ('чтобы', ('чтоб',), 'colloquial_so_that'),
    ('очень', ('оч',), 'colloquial_very'),
    ('прямо', ('прям',), 'colloquial_directly'),
    ('сложно', ('трудно', 'непросто'), 'difficulty'),
    ('трудно', ('сложно', 'непросто'), 'difficulty'),
    ('ничего', ('ничё', 'ничо'), 'colloquial_nothing'),
    ('снова', ('опять',), 'again'),
    ('опять', ('снова',), 'again'),
    ('немного', ('чуть-чуть',), 'small_amount'),
    ('чуть-чуть', ('немного',), 'small_amount'),
    ('наконец-то', ('наконец',), 'finally'),
    ('наконец', ('наконец-то',), 'finally'),
    ('нужно', ('надо',), 'need'),
    ('надо', ('нужно',), 'need'),
    ('отыскать', ('найти',), 'find'),
    ('найти', ('отыскать',), 'find'),
    ('разыскиваю', ('ищу',), 'search'),
    ('ищу', ('разыскиваю',), 'search'),
    ('закончил', ('завершил',), 'finish'),
    ('закончила', ('завершила',), 'finish'),
    ('завершил', ('закончил',), 'finish'),
    ('завершила', ('закончила',), 'finish'),
    ('доделал', ('закончил',), 'finish'),
    ('доделала', ('закончила',), 'finish'),
    ('провалил', ('завалил',), 'failed'),
    ('провалила', ('завалила',), 'failed'),
    ('завалил', ('провалил',), 'failed'),
    ('завалила', ('провалила',), 'failed'),
]
PHRASES = [
    (r'\bпостоянно\b', ('всё время',), 'constant_frequency'),
    # A positive necessity predicate; "не надо" may instead be a prohibition.
    (r'(?<!не )\b(?:нужно|надо)\b', ('необходимо',), 'necessity'),
    (r'\bвпервые\b', ('в первый раз',), 'first_time'),
    (r'\bв первый раз\b', ('впервые',), 'first_time'),
    (r'\bне получается\b', ('не выходит', 'не удаётся'), 'cannot_manage'),
    (r'\bне получилось\b', ('не вышло', 'не удалось'), 'could_not_manage'),
    (r'\bне выходит(?=\s+(?:найти|сделать|начать|закончить|понять|решить|запустить|вспомнить|написать|выбрать)\b)', ('не получается',), 'cannot_manage'),
    (r'\bне вышло(?=\s+(?:найти|сделать|начать|закончить|понять|решить|запустить|вспомнить|написать|выбрать)\b)', ('не получилось',), 'could_not_manage'),
    (r'\bне могу найти\b', ('найти не могу',), 'find_modal_order'),
    (r'\bнайти не могу\b', ('не могу найти',), 'find_modal_order'),
    (r'\bчто делаешь\b', ('чем занят', 'чем занимаешься'), 'activity_question'),
    (r'\bчем занят\b', ('что делаешь',), 'activity_question'),
    (r'\bкак дела\b', ('как сам', 'как поживаешь'), 'wellbeing_question'),
]


def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFC', text).casefold().replace('ё', 'е')))


def initial_upper(text):
    return text[:1].upper() + text[1:]


def sentence_parts(text):
    stripped = text.strip()
    match = re.search(r'[.!?]+$', stripped)
    suffix = match[0] if match else ''
    return (stripped[:-len(suffix)] if suffix else stripped), suffix


def single_clause(text):
    if any(mark in text for mark in LITERAL_MARKERS):
        return None
    body, suffix = sentence_parts(text)
    if re.search(r'[,;:.!?«»"“”]', body):
        return None
    words = body.split()
    if not 2 <= len(words) <= 14:
        return None
    lowered = [word.casefold().replace('ё', 'е') for word in words]
    if set(lowered) & SENSITIVE:
        return None
    return words, lowered, suffix


def lexical_variants(text):
    if any(mark in text for mark in LITERAL_MARKERS):
        return
    for original, replacements, name in LEXICAL:
        pattern = re.compile(r'(?<![\w-])' + re.escape(original) + r'(?![\w-])', re.I)
        if not pattern.search(text):
            continue
        for replacement in replacements:
            result = pattern.sub(lambda match: initial_upper(replacement) if match[0][0].isupper() else replacement, text)
            yield result, name
    for pattern, replacements, name in PHRASES:
        if not re.search(pattern, text, re.I):
            continue
        for replacement in replacements:
            result = re.sub(pattern, lambda match: initial_upper(replacement) if match[0][0].isupper() else replacement, text, flags=re.I)
            yield result, name


def grammatical_variants(text):
    # Present first-person morphology fixes the speaker even when a later clause
    # mentions someone else. Only insert/remove the initial pronoun; the complete
    # remainder, its clauses, negations and participants stay in their places.
    if not any(mark in text for mark in LITERAL_MARKERS):
        body, terminal = sentence_parts(text)
        parts = body.split()
        lower = [part.casefold().replace('ё', 'е').rstrip(',;:.!?') for part in parts]
        first_verb = 1 if lower[:1] == ['не'] else 0
        if first_verb < len(lower) and lower[first_verb] in PRESENT_FIRST_PERSON and 'я' not in lower:
            yield 'Я ' + body[0].lower() + body[1:] + terminal, 'explicit_present_first_person'
        if lower[:1] == ['я'] and lower.count('я') == 1:
            first_verb = 2 if lower[1:2] == ['не'] else 1
            if first_verb < len(lower) and lower[first_verb] in PRESENT_FIRST_PERSON:
                yield initial_upper(' '.join(parts[1:])) + terminal, 'implicit_present_first_person'
    parsed = single_clause(text)
    if parsed is None:
        return
    words, lowered, suffix = parsed
    body = ' '.join(words)
    first = lowered[0]
    # A clearly first-person finite form licenses an explicit first-person pronoun.
    if first in FIRST_PERSON and first not in AMBIGUOUS_PAST | {'заканчиваюсь'} and 'я' not in lowered:
        yield 'Я ' + words[0].lower() + ' ' + ' '.join(words[1:]) + suffix, 'explicit_first_person'
        yield initial_upper(words[0]) + ' я ' + ' '.join(words[1:]) + suffix, 'postverbal_first_person'
    elif (first == 'не' and len(words) >= 3 and lowered[1] in FIRST_PERSON
          and lowered[1] not in AMBIGUOUS_PAST and 'я' not in lowered):
        yield 'Я ' + body[0].lower() + body[1:] + suffix, 'explicit_first_person'
        if lowered[1] in PRESENT_FIRST_PERSON:
            yield initial_upper(' '.join(words[:2])) + ' я ' + ' '.join(words[2:]) + suffix, 'postverbal_first_person'
    elif first == 'я' and len(words) >= 3:
        verb_index = 2 if lowered[1] == 'не' and len(words) > 3 else 1
        if lowered[verb_index] in FIRST_PERSON:
            yield initial_upper(' '.join(words[1:])) + suffix, 'implicit_first_person'
            group = words[1:verb_index + 1]
            yield initial_upper(' '.join(group)) + ' я ' + ' '.join(words[verb_index + 1:]) + suffix, 'postverbal_first_person'
    # Moving a complete short object preserves its internal order and negation.
    offset = 1 if first == 'я' else 0
    verb_index = offset + (1 if lowered[offset] == 'не' else 0)
    if verb_index < len(words) - 1 and lowered[verb_index] in OBJECT_VERBS:
        obj = words[verb_index + 1:]
        obj_lower = lowered[verb_index + 1:]
        other_verbs = set(obj_lower) & FIRST_PERSON
        if 1 <= len(obj) <= 5 and not other_verbs and not (set(obj_lower) & PREPOSITIONS):
            # Do not turn an already fronted adjunct into the grammatical object.
            if obj_lower[0] not in TIME_WORDS | {'не', 'нет', 'очень', 'только', 'уже', 'еще', 'ещё'}:
                verb_group = ' '.join(words[offset:verb_index + 1]).lower()
                yield initial_upper(' '.join(obj)) + ' ' + ('я ' if offset else '') + verb_group + suffix, 'object_fronting'
    if first in TIME_WORDS:
        tail = words[1:]
        if tail and lowered[1] not in TIME_WORDS:
            yield initial_upper(' '.join(tail)) + ' ' + words[0].lower() + suffix, 'time_at_end'
    if lowered[:2] == ['у', 'меня'] and len(words) >= 4 and lowered[2] not in PREPOSITIONS:
        yield initial_upper(' '.join(words[2:])) + ' у меня' + suffix, 'possessor_at_end'
    if first in {'можешь', 'можно'} and len(words) >= 3 and suffix == '?':
        yield initial_upper(' '.join(words[1:])) + ' ' + words[0].lower() + suffix, 'modal_at_end'
    # Keep the infinitival complement intact while moving a modal as one block.
    # Requiring a visible infinitive excludes e.g. "хочу новую игру" and avoids
    # creating a guessed verb or changing which object a modifier belongs to.
    modal_start = 1 if first == 'я' else 0
    modal_verb = modal_start + (1 if lowered[modal_start] == 'не' else 0)
    if modal_verb + 1 < len(words) and lowered[modal_verb] in {'хочу', 'могу'}:
        infinitive = lowered[modal_verb + 1]
        if infinitive.endswith(('ть', 'ться', 'чь')) and not (set(lowered[modal_verb + 2:]) & FIRST_PERSON):
            complement = ' '.join(words[modal_verb + 1:])
            modal = ' '.join(words[modal_start:modal_verb + 1]).lower()
            yield initial_upper(complement) + ' ' + ('я ' if modal_start else '') + modal + suffix, 'modal_complement_fronting'


def variants(text):
    primary = list(lexical_variants(text)) + list(grammatical_variants(text))
    for item in primary:
        yield item
    # Compose at most three independent transformations. The same grammatical
    # family may not be applied twice, preventing pronoun duplication, inverse
    # cycles and arbitrary word permutations. Each step still uses the same
    # bounded whole-clause checks as a direct transformation.
    pronoun_rules = {'explicit_first_person', 'implicit_first_person',
                    'explicit_present_first_person', 'implicit_present_first_person',
                    'postverbal_first_person'}

    def family(rule):
        return 'speaker_position' if rule in pronoun_rules else rule

    seen = {normalized(text)}
    frontier = []
    for phrase, rule in primary:
        key = normalized(phrase)
        if key not in seen:
            seen.add(key)
            frontier.append((phrase, (rule,)))
    for _depth in range(2):
        next_frontier = []
        for phrase, used_rules in frontier:
            used_families = {family(rule) for rule in used_rules}
            next_steps = list(lexical_variants(phrase)) + list(grammatical_variants(phrase))
            for changed, rule in next_steps:
                key = normalized(changed)
                if family(rule) in used_families or key in seen:
                    continue
                seen.add(key)
                path = used_rules + (rule,)
                yield changed, '+'.join(path)
                if len(next_frontier) < 80:
                    next_frontier.append((changed, path))
        frontier = next_frontier
    # One normal conversational preface accompanies an otherwise meaningful change.
    # It is never used as the only transformation for a previously unchanged row.
    if primary:
        phrase, rule = primary[0]
        if not phrase.casefold().startswith(('слушай', 'ну ', 'а ')):
            # Lower known ordinary opening words, while preserving an unknown
            # first token that might be a real person's or place's name.
            common_openings = FIRST_PERSON | TIME_WORDS | {
                'я', 'не', 'нет', 'да', 'мне', 'у', 'в', 'на', 'можно', 'можешь',
                'привет', 'салам', 'как', 'что', 'чем', 'почему', 'где', 'это',
                'найти', 'впервые', 'все', 'всё', 'очень', 'вообще',
            }
            common_openings.update(original for original, _, _ in LEXICAL)
            common_openings.update(value for _, values, _ in LEXICAL for value in values)
            if phrase.split()[0].casefold().rstrip(',!?') in common_openings:
                phrase = phrase[0].lower() + phrase[1:]
            yield 'Слушай, ' + phrase, rule + '+conversational_preface'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/dialogue-combined-5350-v2.sqlite3')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--max-per-source', type=int, default=18)
    parser.add_argument('--overwrite', action='store_true', help='replace an existing candidate export')
    args = parser.parse_args()
    if args.max_per_source < 1:
        parser.error('--max-per-source must be positive')
    if args.database.resolve() == args.output.resolve():
        parser.error('--output must not overwrite the source database')
    if args.output.exists() and not args.overwrite:
        parser.error('Output already exists; choose a new path or pass --overwrite')
    with sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            'SELECT example_id,prompt,answer,context FROM corpus_replies WHERE approved=1 ORDER BY CAST(example_id AS INTEGER)')]
    original_keys = {(normalized(row['context']), normalized(row['prompt'])) for row in rows}
    seen = set(original_keys)
    candidates = []
    rules = Counter()
    source_ids = set()
    for row in rows:
        count = 0
        for candidate, rule in variants(row['prompt']):
            candidate = ' '.join(candidate.split())
            candidate_key = (normalized(row['context']), normalized(candidate))
            if candidate_key in seen or len(candidate) > 400:
                continue
            seen.add(candidate_key)
            candidates.append({'example_id': row['example_id'], 'prompt': candidate,
                               'source_prompt': row['prompt'], 'answer': row['answer'],
                               'context': row['context'], 'transformation': rule})
            rules[rule] += 1
            source_ids.add(row['example_id'])
            count += 1
            if count >= args.max_per_source:
                break
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding='utf-8')
    assert len(candidates) == len({(normalized(row['context']), normalized(row['prompt'])) for row in candidates})
    print(json.dumps({'approved_source_rows': len(rows), 'candidate_variants': len(candidates),
                      'source_rows_with_variants': len(source_ids),
                      'non_preface_variants': sum(value for rule, value in rules.items() if 'preface' not in rule),
                      'transformation_counts': dict(rules), 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
