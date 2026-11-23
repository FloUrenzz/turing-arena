"""Bounded offline retrieval for inputs not covered by exact dialogue rules.

ApproximateIndex(rows).match(question, history=(), context_check=None) returns
{'row': original_row, 'score': float, 'corrections': [(old, new), ...]} or None.
Only approved rows supplied by Corpus are indexed. This module neither opens the
database nor generates answers. A successful result always points to its source.
"""

from collections import Counter, defaultdict
from functools import lru_cache
from heapq import nlargest
import math
import re

from .fuzzy_tokens import normalize_fuzzy, TokenMatcher
from .lexicon import stem


_FAMILIES = {
    'домашка': 'домашка домашку домашки домашкой',
    'задача': 'задача задачу задачи задач задачку задачки задачка',
    'ноутбук': 'ноутбук ноутбука ноутбуке ноутбуку ноут ноуте ноута',
    'компьютер': 'компьютер компьютера компьютере комп компе компа',
    'интернет': 'интернет интернета интернете инет инета инете',
    'книга': 'книга книгу книги книг книжка книжку книжки',
    'телефон': 'телефон телефона телефоне телефону',
    'одежда': 'одежда одежде одежду одежды',
    'пятно': 'пятно пятна пятнышко пятнышка',
    'функция': 'функция функции функций функциям возможность возможности возможностей',
    'нужный': 'нужный нужную нужного нужным требуемый требуемую требуемого требуемым',
    'упаковка': 'упаковка упаковку упаковке упаковки коробка коробку коробке коробки',
    'товар': 'товар товара товаре товару',
    'время': 'время времени временем',
    'мелочь': 'мелочь мелочи мелочам мелочами мелочей',
    'помятый': 'мятая мятой мятый мятую помята помятый помятая помятую помятой',
    'персонаж': 'персонаж персонажа персонажами персонажах герой герои героя героями героях',
    'прежний': 'прежний прежним прежняя прежнее прежние',
    'услышал': 'услышал услышала расслышал расслышала',
    'правлю': 'правлю исправляю',
    'поставил': 'поставил поставила установил установила',
    'нашел': 'нашел нашла отыскал отыскала',
    'найти': 'найти отыскать нахожу',
    'хранить': 'хранить держать',
    'сходил': 'сходил сходила побывал побывала',
    'подошел': 'подошел подошла пришел пришла',
    'приехал': 'приехал приехала подъехал подъехала',
    'заметил': 'заметил заметила обнаружил обнаружила',
    'закончил': 'закончил закончила завершил завершила',
    'согласовать': 'согласовать согласует согласуют договориться',
    'раздражает': 'раздражает раздражают бесит бесят',
    'первый': 'первый первая первое первую первой первом',
    'последний': 'последний последняя последнее последнюю последней последнем',
    'сложно': 'сложно трудно непросто',
    'нужно': 'нужно надо необходимо',
    'сейчас': 'сейчас щас ща',
    'сегодня': 'сегодня сегодняшний сегодняшнего сегодняшним сегодняшняя',
    'вчера': 'вчера вчерашний вчерашнего вчерашним вчерашняя',
    'завтра': 'завтра завтрашний завтрашнего завтрашним завтрашняя',
    'летом': 'летом летний летняя летнее',
    'зимой': 'зимой зимний зимняя зимнее',
    'широкий': 'широкий широкая широкое широкой широкую широком',
    'узкий': 'узкий узкая узкое узкой узкую узком',
    'быстро': 'быстро быстрее быстрый быстрая',
    'медленно': 'медленно медленнее медленный медленная',
    'плохо': 'плохо плохое плохой плохая',
    'хорошо': 'хорошо хорошее хороший хорошая',
    'грустно': 'грустно печально',
    'снова': 'снова опять',
}
_ALIASES = {word: family for family, forms in _FAMILIES.items() for word in forms.split()}
_PHRASES = {
    ('домашнее', 'задание'): ('домашка',),
    ('домашнего', 'задания'): ('домашка',),
    ('онлайн', 'пару'): ('онлайн-пару',),
    ('онлайн', 'пара'): ('онлайн-пара',),
    ('все', 'тот', 'же'): ('прежний',),
    ('тот', 'же'): ('прежний',),
    ('не', 'могу', 'найти'): ('не', 'найти'),
    ('не', 'могу', 'отыскать'): ('не', 'найти'),
    ('не', 'получается', 'найти'): ('не', 'найти'),
    ('не', 'дает', 'договорить'): ('перебивает',),
    ('в', 'первый', 'раз'): ('впервые',),
    ('первый', 'раз'): ('впервые',),
    ('в', 'данный', 'момент'): ('сейчас',),
}
_STOP = set('''
я ты мы вы он она они у в во на и а но же то вот это как что мне тебя меня тебе
уже вообще очень пожалуйста ну да просто аж все сам сама тоже так еще эту этот
эти свой свою свое свои мой моя мое мои его ее их теперь совсем случайно никак
разные разными разный разных немного чуть было была был есть какой какая какое
которые который которая чтоб чтобы
о об по про с со из за от к ко для наша наш наши своего даже себе
'''.split())
_NEGATIVE = {'не', 'нет', 'без', 'никогда', 'никто', 'ничего', 'ничто', 'ни'}
_TIMES = set('сегодня вчера завтра послезавтра позавчера сейчас летом зимой весной осенью'.split())
_CRITICAL = set('быстро медленно широкий узкий только почти едва всегда никогда одновременно поочередно первый последний'.split())
_RELATIONS = {'до': 'before', 'перед': 'before', 'после': 'after', 'вместо': 'instead', 'между': 'between'}
_EVENT_ORDER = {'сначала', 'потом', 'затем', 'раньше', 'позже', 'прежде'}
_ROLES = {
    'я': ('self', 'subject'), 'мне': ('self', 'object'), 'меня': ('self', 'object'),
    'ты': ('addressee', 'subject'), 'тебе': ('addressee', 'object'), 'тебя': ('addressee', 'object'),
    'друг': ('friend', 'subject'), 'друга': ('friend', 'object'), 'другу': ('friend', 'object'),
    'подруга': ('friend_f', 'subject'), 'подруги': ('friend_f', 'object'), 'подруге': ('friend_f', 'object'),
    'мама': ('mother', 'subject'), 'маму': ('mother', 'object'), 'маме': ('mother', 'object'),
    'папа': ('father', 'subject'), 'папу': ('father', 'object'), 'папе': ('father', 'object'),
    'брат': ('brother', 'subject'), 'брата': ('brother', 'object'), 'брату': ('brother', 'object'),
    'сестра': ('sister', 'subject'), 'сестру': ('sister', 'object'), 'сестре': ('sister', 'object'),
    'он': ('other_m', 'subject'), 'она': ('other_f', 'subject'), 'они': ('others', 'subject'),
    'ему': ('other_m', 'object'), 'ей': ('other_f', 'object'), 'им': ('others', 'object'),
}
_NUMBERS = {}
for _number, _forms in enumerate((
    'ноль нуля нулю нулем', 'один одна одно одну одного одной единственный единственным',
    'два две двух двум двумя', 'три трех трем тремя', 'четыре четырех четырем четырьмя',
    'пять пяти пятью', 'шесть шести шестью', 'семь семи семью', 'восемь восьми восемью',
    'девять девяти девятью', 'десять десяти десятью',
)):
    _NUMBERS.update({word: str(_number) for word in _forms.split()})
_NUMBERS.update(dict(zip('одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто тысяча миллион'.split(),
                        map(str, (11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 30, 40, 50, 60, 70, 80, 90, 100, 1000, 1000000)))))
_WH_GROUPS = (
    ('why', {'почему', 'отчего'}), ('purpose', {'зачем'}),
    ('where', {'где', 'куда', 'откуда'}), ('when', {'когда'}),
    ('quantity', {'сколько'}), ('how', {'как'}), ('what', {'что', 'чем', 'какой', 'какая', 'какое'}),
)
_WH_WORDS = set().union(*(group for _, group in _WH_GROUPS))
_FIRST_VISITS = {'концерт', 'концерте', 'тренировку', 'тренировка', 'тренировке', 'секцию', 'секция'}
_NUMBER_PATTERN = re.compile(r'[+\-]?\d+(?:[.,]\d+)?')
_PROTECTED = _NEGATIVE | _TIMES | _CRITICAL | _EVENT_ORDER | set(_RELATIONS) | set(_ROLES) | set(_NUMBERS)
_QUOTES = set('«»"“”‘’`\'')
_VERB_ENDING = re.compile(r'.{2,}(?:л|ла|ли|лся|лась|лись|лось|ешь|ете|ют|ут|ят|ит|ет|ить|ать|ять|еть|нуть|ться|юсь|аю|яю|лю)$')


def _semantic_tokens(surface):
    words, index = [], 0
    while index < len(surface):
        replacement = None
        for size in (3, 2):
            replacement = _PHRASES.get(tuple(surface[index:index + size]))
            if replacement is not None:
                words.extend(replacement)
                index += size
                break
        if replacement is None:
            words.append(surface[index])
            index += 1
    words = [_ALIASES.get(word, word) for word in words]
    # "Первый концерт" after a visit is an experience, not a numbered item.
    if 'сходил' in words:
        words = ['впервые' if word == 'первый' and index + 1 < len(words)
                 and words[index + 1] in _FIRST_VISITS else word
                 for index, word in enumerate(words)]
    # The modal is optional in an inability statement; retain the negation target.
    words = [word for index, word in enumerate(words)
             if not (word in {'могу', 'может', 'можем', 'могут'} and index > 0
                     and words[index - 1] == 'не' and index + 1 < len(words)
                     and words[index + 1].endswith(('ть', 'ться')))]
    return words


def _number(word):
    if word in _NUMBERS:
        return _NUMBERS[word]
    if _NUMBER_PATTERN.fullmatch(word):
        return word.lstrip('+').replace(',', '.')
    return None


def _content_key(word):
    return _number(word) or stem(word)


def _next_content(words, start):
    return next((_content_key(word) for word in words[start:] if word not in _STOP and word not in _NEGATIVE), '')


def _negative_target(words, start):
    for index in range(start, len(words)):
        word = words[index]
        if word in _STOP or word in _NEGATIVE:
            continue
        # "не хочу смотреть, хочу читать" must not negate the other activity.
        # Repeated predicates also need their object to identify the clause.
        extend = word in {'хочу', 'хочет', 'хотим', 'люблю', 'любит', 'буду', 'будет',
                          'стал', 'стала', 'можно', 'нужно', 'стоит', 'получается'} or words.count(word) > 1
        return (_content_key(word), _next_content(words, index + 1) if extend else '')
    return ('', '')


def _guards(text, words):
    """Protected meaning is never traded away for a high lexical overlap."""
    roles = []
    for index, word in enumerate(words):
        if word in _ROLES:
            actor, role = _ROLES[word]
            if index and (words[index - 1] == 'у' or
                          (word in {'друга', 'подруги', 'брата'} and words[index - 1] == 'рождения')):
                role = 'possessor'
            roles.append((actor, role))
    third = [role for role in roles if role[0] not in ('self', 'addressee')]
    if len(third) > 1:
        return None
    if third and sum(role == 'subject' for _, role in roles) > 1:
        # A bag of words cannot assign predicates across multiple subjects:
        # "друг сказал, что я опоздал" is not "я сказал, что друг опоздал".
        return None
    if not third:
        roles = [role for role in roles if role[0] == 'addressee']
    else:
        roles = [role for role in roles if role != ('self', 'subject')]
    polarity = tuple(sorted((word, _negative_target(words, index + 1)) for index, word in enumerate(words) if word in _NEGATIVE))
    quantities = tuple(sorted((value, _next_content(words, index + 1))
                              for index, word in enumerate(words) if (value := _number(word)) is not None))
    times = frozenset(word for word in words if word in _TIMES)
    qualifiers = tuple(sorted((word, _next_content(words, index + 1)) for index, word in enumerate(words) if word in _CRITICAL))
    relations = tuple(sorted((_RELATIONS[word], _next_content(words, index + 1))
                             for index, word in enumerate(words) if word in _RELATIONS))
    events = tuple((word, _next_content(words, index + 1)) for index, word in enumerate(words) if word in _EVENT_ORDER)
    # Relative clauses ("вспомнил, что...", "неприятно, когда...") do not
    # change a statement into a what/when question.
    starts_question = bool(words and words[0] in _WH_WORDS)
    act = 'question' if '?' in text or starts_question else 'statement'
    word_set = set(words)
    kind = next((kind for kind, group in _WH_GROUPS if word_set & group), None) if act == 'question' else None
    return tuple(sorted(set(roles))), polarity, quantities, times, qualifiers, relations, events, kind, act


@lru_cache(maxsize=16384)
def _prepare(text, surface_override=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 600 or '\n' in text or any(char in text for char in _QUOTES):
        return None
    if re.search(r'[+*/%=<>]', text) or '?' in text.rstrip(' ?!.'):
        return None
    surface = tuple(surface_override) if surface_override is not None else tuple(normalize_fuzzy(text))
    words = _semantic_tokens(surface)
    if not 2 <= len(words) <= 70:
        return None
    guards = _guards(text, words)
    if guards is None:
        return None
    sequence = tuple(_content_key(word) for word in words if word not in _STOP and word not in _NEGATIVE)
    terms = frozenset(sequence)
    if len(terms) < 2:
        return None
    verbs = tuple(_content_key(word) for word in words if _VERB_ENDING.fullmatch(word))
    return {'terms': terms, 'sequence': sequence, 'guards': guards, 'verbs': verbs, 'surface': surface}


def _ordered_common(left, right):
    # At most 70 words. Count common ordered adjacent pairs as a small tie-breaker.
    if len(left) < 2 or len(right) < 2:
        return 1.0
    pairs_left, pairs_right = set(zip(left, left[1:])), set(zip(right, right[1:]))
    return len(pairs_left & pairs_right) / max(1, min(len(pairs_left), len(pairs_right)))


class ApproximateIndex:
    def __init__(self, rows):
        self.documents = []
        vocabulary = set(_ALIASES) | _PROTECTED
        for row in rows:
            vocabulary.update(normalize_fuzzy(row['prompt']))
            prepared = _prepare(row['prompt'])
            if prepared is not None:
                self.documents.append((row, prepared))
        self.token_matcher = TokenMatcher(vocabulary, protected=_PROTECTED)
        self.vocabulary = frozenset(vocabulary)
        frequencies = Counter(term for _, prepared in self.documents for term in prepared['terms'])
        self.idf = {term: 1 + math.log((len(self.documents) + 1) / (count + 1)) for term, count in frequencies.items()}
        self.postings = defaultdict(list)
        self.document_weights = []
        for index, (_, prepared) in enumerate(self.documents):
            for term in prepared['terms']:
                self.postings[term].append(index)
            self.document_weights.append(sum(self.idf[term] for term in prepared['terms']))

    def match(self, question, history=(), context_check=None):
        if not isinstance(question, str) or len(question) > 600 or any(char in question for char in _QUOTES):
            return None
        surface = normalize_fuzzy(question)
        # Unknown title-case nouns may be names. Do not turn Арман into карман.
        names = {word.casefold().replace('ё', 'е') for word in re.findall(r'\b[А-ЯЁA-Z][а-яёa-z]{2,}\b', question)
                 if word.casefold().replace('ё', 'е') not in self.vocabulary and not _VERB_ENDING.fullmatch(word.casefold())}
        corrected, corrections = self.token_matcher.correct(surface)
        rejected = {old for old, new in corrections if old in names
                    and not (surface and old == surface[0] and old[0] == new[0]
                             and (old[-2:] == new[-2:] or (new in _ALIASES and old[-1] == new[-1])))}
        corrected = [old if old in rejected else new for old, new in zip(surface, corrected)]
        corrections = [(old, new) for old, new in corrections if old not in rejected]
        query = _prepare(question, tuple(corrected))
        if query is None:
            return None
        # Unresolved content words are evidence of a new relation, not noise.
        if any(term not in self.idf for term in query['terms']):
            return None
        query_weight = sum(self.idf[term] for term in query['terms'])
        overlap = defaultdict(float)
        for term in query['terms']:
            for index in self.postings.get(term, ()):
                overlap[index] += self.idf[term]
        candidates = nlargest(150, overlap, key=overlap.get)
        matches = []
        for index in candidates:
            row, document = self.documents[index]
            if query['guards'] != document['guards']:
                continue
            common = query['terms'] & document['terms']
            if len(common) < 2:
                continue
            query_coverage = overlap[index] / query_weight
            document_coverage = overlap[index] / self.document_weights[index]
            if query_coverage < .90 or document_coverage < .72:
                continue
            # Preserve event sequence when multiple recognizable predicates occur.
            shared_verbs = set(query['verbs']) & set(document['verbs'])
            if len(shared_verbs) > 1:
                left = tuple(word for word in query['verbs'] if word in shared_verbs)
                right = tuple(word for word in document['verbs'] if word in shared_verbs)
                if left != right:
                    continue
            if context_check is not None:
                if not context_check(row, history):
                    continue
            elif row.get('context') or row.get('context_turns'):
                continue
            dice = 2 * overlap[index] / (query_weight + self.document_weights[index])
            score = .98 * dice + .02 * _ordered_common(query['sequence'], document['sequence'])
            if score >= .84:
                matches.append((score, row))
        matches.sort(key=lambda item: (-item[0], str(item[1].get('id', ''))))
        if not matches:
            return None
        score, row = matches[0]
        if any(score - other_score < .07 and other['answer'] != row['answer'] for other_score, other in matches[1:]):
            return None
        return {'row': row, 'score': round(score, 4), 'corrections': corrections}
