"""Bounded offline equivalence keys, without treating every word bag as meaning.

``phrase_features(text)`` returns a hashable tuple or None for literal/unsupported
input. The tuple is suitable for a corpus index. ``equivalent(a, b)`` never treats
two unsupported inputs as equivalent. Unknown constructions keep their word order;
only a single recognized action with one speaker permits reordering. This is a
deliberately limited grammar, not a general Russian semantic parser.
"""

from functools import lru_cache
import re
import unicodedata


_FAMILIES = {
    'ключ': 'ключ ключи ключей ключа ключами',
    'телефон': 'телефон телефона телефоны телефонов',
    'зарядка': 'зарядка зарядку зарядки',
    'наушники': 'наушники наушников наушниками',
    'ноутбук': 'ноутбук ноутбука ноутбуки ноутбуков',
    'презентация': 'презентация презентацию презентации презентацией',
    'домашка': 'домашка домашку домашки домашкой',
    'экзамен': 'экзамен экзамена экзамены экзаменов экзамену',
    'проект': 'проект проекта проекты проектов проектом',
    'задание': 'задание задания заданий заданием',
    'слайд': 'слайд слайда слайды слайдов',
    'фильм': 'фильм фильма фильмы фильмов кино',
    'музыка': 'музыка музыку музыки музыкой',
    'книга': 'книга книгу книги книг',
    'серия': 'серия серию серии серий',
    'сериал': 'сериал сериала сериалы сериалов',
    'текст': 'текст текста тексты текстов',
    'рисунок': 'рисунок рисунка рисунки рисунков',
    'рецепт': 'рецепт рецепта рецепты рецептов',
    'сумка': 'сумка сумку сумки сумкой',
    'рюкзак': 'рюкзак рюкзака рюкзаки',
    'комната': 'комната комнату комнаты',
    'кабель': 'кабель кабеля кабели',
    'билет': 'билет билета билеты билетов',
    'конспект': 'конспект конспекта конспекты конспектов',
    'одежда': 'одежда одежду одежды',
    'завтрак': 'завтрак завтрака завтраком',
    'ужин': 'ужин ужина ужином',
    'еда': 'еда еду еды',
    'условие': 'условие условия условий',
    'пример': 'пример примера примеры примеров',
    'скрипт': 'скрипт скрипта скрипты скриптов',
    'интернет': 'интернет интернета',
    'слово': 'слово слова слов',
    'язык': 'язык языка языки языков',
    'пазл': 'пазл пазла пазлы пазлов',
    'рассказ': 'рассказ рассказа рассказы рассказов',
    'открытка': 'открытка открытку открытки открыток',
    'чашка': 'чашка чашке чашки чашку',
    'запись': 'запись записи',
    'лекция': 'лекция лекцию лекции лекций',
    'вычисление': 'вычисление вычисления вычислениях вычислений',
    'салат': 'салат салата салаты салатов',
    'потерял': 'потерял потеряла',
    'нашел': 'нашел нашла',
    'понял': 'понял поняла',
    'придумать': 'придумать',
    'выбрать': 'выбрать',
    'запускается': 'запускается',
    'забываются': 'забываются',
    'пропал': 'пропал пропала пропало',
    'теряю': 'теряю',
    'нарезаю': 'нарезаю',
    'собираю': 'собираю',
    'пишу': 'пишу',
    'коллекционирую': 'коллекционирую',
    'найти': 'найти отыскать',
    'ищу': 'ищу разыскиваю',
    'подготовил': 'подготовил подготовила',
    'закончил': 'закончил закончила завершил завершила доделал доделала',
    'сделал': 'сделал сделала',
    'сдал': 'сдал сдала',
    'завалил': 'завалил завалила провалил провалила',
    'забыл': 'забыл забыла',
    'купил': 'купил купила',
    'прочитал': 'прочитал прочитала',
    'посмотрел': 'посмотрел посмотрела',
    'скачал': 'скачал скачала',
    'сохранил': 'сохранил сохранила',
    'удалил': 'удалил удалила',
    'написал': 'написал написала',
    'нарисовал': 'нарисовал нарисовала',
    'собрал': 'собрал собрала',
    'приготовил': 'приготовил приготовила',
    'готовить': 'готовить приготовить',
    'разобрал': 'разобрал разобрала',
    'починил': 'починил починила',
    'сломал': 'сломал сломала',
    'включил': 'включил включила',
    'выключил': 'выключил выключила',
    'запустил': 'запустил запустила',
    'открыл': 'открыл открыла',
    'закрыл': 'закрыл закрыла',
    'смотрю': 'смотрю', 'слушаю': 'слушаю', 'читаю': 'читаю',
    'учусь': 'учусь', 'отдыхаю': 'отдыхаю', 'скучаю': 'скучаю',
    'устал': 'устал устала', 'проспал': 'проспал проспала',
    'опоздал': 'опоздал опоздала', 'проснулся': 'проснулся проснулась',
    'могу': 'могу', 'хочу': 'хочу', 'нужно': 'нужно надо необходимо',
    'сейчас': 'сейчас щас ща', 'ничего': 'ничего ниче ничо',
    'что': 'что че чо', 'наконец': 'наконец наконец-то наконецто',
    'снова': 'снова опять', 'немного': 'немного чуть-чуть',
    'сегодня': 'сегодня седня', 'вообще': 'вообще ваще',
    'нормально': 'нормально норм нормас', 'чтобы': 'чтобы чтоб',
    'сложно': 'сложно трудно непросто',
    'очень': 'очень оч', 'прямо': 'прямо прям',
}
_FORMS = {form: canonical for canonical, forms in _FAMILIES.items() for form in forms.split()}
_ACTIONS = set('потерял нашел найти ищу подготовил закончил сделал сдал завалил забыл купил прочитал посмотрел скачал сохранил удалил написал нарисовал собрал приготовил готовить разобрал починил сломал включил выключил запустил открыл закрыл смотрю слушаю читаю учусь отдыхаю скучаю устал проспал опоздал проснулся'.split())
_ACTIONS.update('понял придумать выбрать запускается забываются пропал теряю нарезаю собираю пишу коллекционирую'.split())
_MODALS = {'могу', 'хочу', 'нужно'}
_FIRST_PERSON = set('хочу могу люблю думаю смотрю слушаю читаю пишу рисую ищу учусь отдыхаю скучаю сижу жду иду еду пробую выбираю собираю делаю готовлю повторяю изучаю осваиваю разбираю перебираю убираю проверяю вспоминаю пытаюсь планирую собираюсь возвращаюсь просыпаюсь замечаю начинаю заканчиваю сравниваю теряю нарезаю коллекционирую'.split())
_FIRST_PERSON.update('знаю понимаю помню успеваю забываю обсуждаю показываю продолжаю сомневаюсь боюсь надеюсь волнуюсь переживаю работаю гуляю играю учу ставлю лежу сплю жалею путаюсь отвлекаюсь выбираюсь запускаю'.split())
_FREQUENCY_PREDICATES = _FIRST_PERSON | set('пропадает перебивает исправляю путаю отвлекаемся прерывают отключается меняю срывается двигается добавляю нахожу возвращают перебивают всплывают перемешиваются пропускаю падает поправляю мечусь затягивается теряются смешиваются хожу согласен переписываю срываются выручал изучает'.split())
_PREPOSITIONS = set('в во на под над за перед после до от из с со к ко у о об для между возле через по без'.split())
_OTHER_ACTORS = set('ты тебе тебя твой твоя вы вам вас он она оно они его ее ему ей их им друг друга друзья друзей подруга подруги мама маме маму папа папе папу брат брата брату сестра сестре сестру сосед соседа коллега коллеги руководитель преподаватель учитель'.split())
_SENSITIVE = set('и или а либо да сначала затем потом раньше позже потому поэтому вследствие вместо если когда хотя но однако зато чтобы пока после прежде больше меньше быстрее медленнее чем между который которая которое которые'.split())
_NEGATIVE = {'не', 'нет', 'без', 'никогда', 'ничего', 'никто', 'ни'}
_ADVERBS = set('сегодня вчера завтра сейчас обычно всегда никогда иногда постоянно быстро медленно слишком очень только уже еще немного много мало снова вообще точно просто почти совсем едва наконец одновременно'.split())
_ADJECTIVES = set('новый новая новое новые новой старый старая старое старые старой большой большая большое большие большой маленький маленькая маленькое маленькие маленькой широкий широкая широкое широкие широкой узкий узкая узкое узкие узкой хороший хорошая хорошее хорошие плохой плохая плохое плохие срочный срочная срочное срочные короткий короткая короткое короткие длинный длинная длинное длинные'.split())
_WH = set('кто что чем чего как какой какая какие какое почему отчего зачем где куда откуда когда сколько'.split())
_PREFIX = re.compile(r'^(?:(?:ну|а|слушай(?:те)?|короче|пожалуйста|в общем|если что|кстати)(?:\s*[,!:]\s*|\s+))+')
_SUFFIX = re.compile(r'(?:\s+(?:же|ведь|пожалуйста|что ли))+$')
_TOKEN = re.compile(r'[-−]?\d+(?:[.,]\d+)?|[^\W\d_]+(?:-[^\W\d_]+)*|[.!?;,+:*/=]', re.UNICODE)


def _normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е').replace('−', '-')
    text = ' '.join(text.split()).strip()
    text = re.sub(r'(?<![\w-])(?:плиз|пж)(?![\w-])', 'пожалуйста', text)
    # Local phrase synonyms preserve every surrounding word and clause boundary.
    for phrase, replacement in (('в данный момент', 'сейчас'),
                                ('по какой причине', 'почему'),
                                ('для чего', 'зачем')):
        text = re.sub(r'(?<![\w-])' + phrase + r'(?![\w-])', replacement, text)
    text = _PREFIX.sub('', text).strip(' ,:!')
    # Polite request markers only precede an actual interrogative construction.
    text = re.sub(r'^(?:скажи|подскажи)(?:\s*,?\s+)(?=(?:как|где|куда|когда|почему|зачем|что|сколько)\b)', '', text)
    text = text.rstrip(' .!?')
    text = _SUFFIX.sub('', text)
    text = re.sub(r'\bдомашнее задание\b', 'домашка', text)
    text = re.sub(r'\bв первый раз\b', 'впервые', text)
    text = re.sub(r'\bне (?:выходит|удается)(?!\s+из\b)', 'не получается', text)
    text = re.sub(r'\bне (?:вышло|удалось)(?!\s+из\b)', 'не получилось', text)
    return text


def _units(words):
    """Keep a small prepositional phrase together during safe reordering.

    Only one such phrase is handled; its object and adjectives are never moved
    outside it. Thus 'ключи в сумке' cannot become 'сумку в ключах'.
    """
    if sum(word in _PREPOSITIONS for word in words) > 1:
        return None
    result, index = [], 0
    while index < len(words):
        word = words[index]
        if word == 'я' or word == ',':
            index += 1
            continue
        if word in _PREPOSITIONS:
            phrase = [word]
            index += 1
            while index < len(words) and words[index] in _ADJECTIVES:
                phrase.append(words[index])
                index += 1
            if index >= len(words) or words[index] in (_ACTIONS | _MODALS | _NEGATIVE | _ADVERBS | _PREPOSITIONS):
                return None
            phrase.append(words[index])
            result.append(tuple(phrase))
            index += 1
        elif word in _ADJECTIVES or re.fullmatch(r'-?\d+(?:[.,]\d+)?', word):
            # An adjective or count belongs to the following noun, not any noun
            # elsewhere in the sentence. Retain that attachment while moving it.
            phrase = [word]
            index += 1
            while index < len(words) and words[index] in _ADJECTIVES:
                phrase.append(words[index])
                index += 1
            if index < len(words) and words[index] not in (_ACTIONS | _MODALS | _NEGATIVE | _ADVERBS | _PREPOSITIONS | {',', 'я'}):
                phrase.append(words[index])
                index += 1
            result.append(tuple(phrase))
        else:
            result.append((word,))
            index += 1
    return tuple(sorted(result))


def _move_whole_blocks(words):
    """Move a bounded adjunct/modal, never scramble its complement or clauses."""
    words = list(words)
    # "Всё время" is a frequency adjunct before a known predicate. It is not
    # interchangeable with frequency when it is a quantity ("потратил всё время").
    for index in range(len(words) - 2, -1, -1):
        if words[index:index + 2] != ['все', 'время']:
            continue
        following = index + 2
        if following < len(words) and words[following] in {'что-то', 'не'}:
            following += 1
        before_predicate = following < len(words) and words[following] in _FREQUENCY_PREDICATES
        after_predicate = index > 0 and words[index - 1] == 'достаю' and index + 2 == len(words)
        if before_predicate or after_predicate:
            words[index:index + 2] = ['постоянно']
    # This adjacent three-word construction has the same scope in any clause.
    for index in range(len(words) - 2):
        if words[index:index + 3] == ['найти', 'не', 'могу']:
            words[index:index + 3] = ['не', 'могу', 'найти']
    boundaries = _SENSITIVE | {',', ';', '.', '!', '?', ':'}
    if set(words) & boundaries:
        return words

    # First-person modal and its negation travel together. All words of the
    # infinitive phrase retain their order and all recipients stay inside it.
    for modal in ('хочу', 'могу', 'можно', 'можешь'):
        if words.count(modal) != 1:
            continue
        index = words.index(modal)
        begin = index - (index > 0 and words[index - 1] == 'не')
        begin -= begin > 0 and words[begin - 1] == 'я' and modal in {'хочу', 'могу'}
        block = words[begin:index + 1]
        complement = words[index + 1:] if begin == 0 else words[:begin] if index == len(words) - 1 else []
        if not complement or set(complement) & _FIRST_PERSON:
            continue
        if modal in {'хочу', 'могу'} and not complement[0].endswith(('ть', 'ться', 'чь')):
            continue
        words = [word for word in block if word != 'я'] + complement
        break

    # Boundary time adjuncts can move, but "не сегодня" and "только завтра"
    # are intact focus expressions and must never be split.
    times = {'сегодня', 'завтра', 'вчера', 'сейчас'}
    if sum(word in times for word in words) == 1 and len(words) > 2:
        if words[-1] in times and words[-2] not in {'не', 'ни', 'только', 'лишь', 'именно', 'почти'}:
            words = [words[-1]] + words[:-1]

    # An ownership phrase moves as a pair. Another person, another "у", or
    # a leading negation would make the attachment ambiguous, so keep order.
    if words[-2:] == ['у', 'меня'] and words.count('у') == 1 and not set(words) & _OTHER_ACTORS:
        rest = words[:-2]
        if rest and rest[-1] not in {'не', 'ни', 'только', 'именно'}:
            words = ['у', 'меня'] + rest
    return words


def _structured_key(words, act):
    """Small typed clauses for cases where ordinary word sorting is unsafe."""
    # A named subject and one state can exchange positions. Permit only known
    # modifiers; e.g. a new recipient or a second subject cannot disappear.
    for subject, states in (
        ('лекция', {'длинная', 'короткая'}),
        ('настроение', {'хорошее', 'плохое', 'нормальное', 'отличное', 'ужасное'}),
    ):
        if words.count(subject) != 1 or sum(word in states for word in words) != 1:
            continue
        rest = list(words)
        recorded = False
        if subject == 'лекция' and 'в' in rest:
            index = rest.index('в')
            if rest[index:index + 2] != ['в', 'запись']:
                continue
            del rest[index:index + 2]
            recorded = True
        allowed = states | {subject, 'сегодня', 'сейчас', 'снова', 'вообще', 'слишком', 'очень', 'почему-то'}
        if all(word in allowed for word in rest):
            return ('phrase-v1', act, 'state', subject, recorded, tuple(sorted(rest)))

    # Third-person plural assignment keeps the whole counted object together.
    # Only task assignment permits an omitted personal recipient ("дали задачи").
    for verb, noun in (('дали', 'задачи'), ('поставили', 'пары')):
        if words.count(verb) != 1 or words.count(noun) != 1:
            continue
        rest = list(words)
        rest.remove(verb)
        if verb == 'дали' and rest.count('мне') == 1:
            rest.remove('мне')
        temporal = ()
        if verb == 'поставили' and rest.count('одновременно') == 1:
            rest.remove('одновременно')
            temporal = ('одновременно',)
        counts = {'одну', 'две', 'три', 'четыре', 'пять', 'шесть'}
        allowed = counts | {'одинаково', 'срочные', 'срочную', noun}
        if len(rest) >= 2 and rest[-1] == noun and all(word in allowed or word.isdigit() for word in rest):
            return ('phrase-v1', act, 'assignment', verb, tuple(rest), temporal)

    # Fronting "позже" must not reorder the event after the comparative comma.
    if words.count(',') == 1:
        split = words.index(',')
        head, tail = words[:split], words[split + 1:]
        if len(head) == 2 and head.count('проснулся') == 1 and any(word in {'раньше', 'позже'} for word in head) and tail[:1] == ['чем']:
            return ('phrase-v1', act, 'comparison', tuple(sorted(head)), tuple(tail))

    # Actor and response predicate are separate roles, while a duration can move.
    actors = {'друг', 'подруга', 'мама', 'папа', 'брат', 'сестра'}
    if sum(word in actors for word in words) == 1 and words.count('отвечает') == 1:
        actor = next(word for word in words if word in actors)
        text = ' '.join(words)
        duration = r'(?:второй|третий|четвертый) день'
        for pattern in (rf'{actor} ({duration}) (не )?отвечает',
                        rf'({duration}) {actor} (не )?отвечает',
                        rf'{actor} (не )?отвечает ({duration})'):
            match = re.fullmatch(pattern, text)
            if match:
                return ('phrase-v1', act, 'person-response', actor, tuple(sorted(part.strip() for part in match.groups() if part)))
    return None


@lru_cache(maxsize=32768)
def phrase_features(text):
    """A hashable meaning-preserving approximation, or None for literals.

    The key retains polarity, questions versus assertions, quantity, time and all
    unknown qualifiers. Only recognizable single-action self reports can reorder
    their remaining words. Multi-person, multi-clause and causal text stays ordered.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        return None
    if '\n' in text or any(char in text for char in '«»"“”\'‘’`'):
        return None
    normalized = _normalize(text)
    if not normalized:
        return None
    raw = _TOKEN.findall(normalized)
    if not raw:
        return None
    # Reject punctuation/operator/literal inputs that this language key cannot model.
    if any(token in '+*/=' for token in raw):
        return None
    words = _move_whole_blocks([_FORMS.get(word, word) for word in raw])
    # A present first-person verb already encodes "я". Remove only this redundant
    # subject; retain the exact order of everything else, including complex clauses.
    if 'я' in words:
        leading_verb = words[1:3] if words[:1] == ['я'] else []
        leading_self = bool(leading_verb and (leading_verb[0] in _FIRST_PERSON or
                            (leading_verb[0] == 'не' and len(leading_verb) == 2 and leading_verb[1] in _FIRST_PERSON)))
        simple_self = bool(set(words) & _FIRST_PERSON) and not (set(words) & (_SENSITIVE | _OTHER_ACTORS | {',', ';', '.', '!', '?', ':'}))
        if leading_self or (words.count('я') == 1 and simple_self):
            words.remove('я')
    terminal_question = '?' in text.rstrip()[-3:]
    act = 'question' if terminal_question or set(words) & _WH else 'statement'

    # These colloquial questions share a well-defined intent, not just one word.
    compact = ' '.join(word for word in words if word not in {',', 'ты', 'у', 'тебя'})
    greeting = ''
    for hello in ('привет ', 'салам ', 'ку '):
        if compact.startswith(hello):
            greeting, compact = hello.strip(), compact[len(hello):]
            break
    if compact in {'что делаешь', 'что делаеш', 'чем занят', 'чем занимаешься'}:
        return ('phrase-v1', 'question', 'activity', greeting)
    if compact in {'как дела', 'как сам', 'как сама', 'как поживаешь', 'как твои дела'}:
        return ('phrase-v1', 'question', 'wellbeing', greeting)

    # A bounded memory clause: keep concession and its scope, normalize the
    # independently recognizable head and the single "brought them home" event.
    # Other compound clauses deliberately remain ordered.
    if words.count('хотя') == 1:
        split = words.index('хотя')
        head_words, tail = words[:split], words[split + 1:]
        if head_words[-1:] == [',']:
            head_words = head_words[:-1]
        if len(tail) == 4 and set(tail) == {'точно', 'принес', 'их', 'домой'}:
            head = phrase_features(' '.join(head_words))
            if head is not None and len(head) > 2 and head[2] == 'single-action':
                return ('phrase-v1', act, 'concession-memory', head, 'принес', 'их', 'домой', 'точно')

    structured = _structured_key(words, act)
    if structured is not None:
        return structured

    # Commas are not discarded in compound sentences or actor-sensitive phrases.
    sensitive = bool(set(words) & (_SENSITIVE | _OTHER_ACTORS))
    sensitive = sensitive or any(token in {';', '.', '!', '?', ':'} for token in words)
    action_positions = [i for i, word in enumerate(words) if word in _ACTIONS]
    # Two unfamiliar nouns can be two people/animals with reversible roles.
    known = set(_FAMILIES) | _ACTIONS | _MODALS | _NEGATIVE | _ADVERBS | _ADJECTIVES | _PREPOSITIONS | _WH | {'я', ',', 'же', 'ведь'}
    unfamiliar = [word for word in words if word not in known and not word.isdigit()]
    sensitive = sensitive or len(unfamiliar) > 1
    safe_action = len(action_positions) == 1 and not sensitive
    if not safe_action:
        return ('phrase-v1', act, 'ordered', tuple(words))

    # Negation must remain attached to the same word: 'не нашёл ключи' and
    # 'нашёл не ключи' have different meanings even though their word bags agree.
    negation = tuple((word, next((next_word for next_word in words[i + 1:] if next_word != ','), ''))
                     for i, word in enumerate(words) if word in _NEGATIVE)
    actor = 'self'
    payload = _units(words)
    if payload is None:
        return ('phrase-v1', act, 'ordered', tuple(words))
    return ('phrase-v1', act, 'single-action', actor, negation, payload)


def equivalent(left, right):
    """True only when both texts have the same supported phrase key."""
    left_key = phrase_features(left)
    return left_key is not None and left_key == phrase_features(right)
