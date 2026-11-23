"""Recognize self-introductions without enumerating people's names."""

import re
import unicodedata


_PREFACE = re.compile(
    r"^(?:(?:привет|салам|салем|сәлем|ку|хай|здравствуй(?:те)?|"
    r"добрый (?:день|вечер)|кстати|ну|нет|точнее|вообще-то|короче|"
    r"в общем|если что|на самом деле|ты перепутал|поправлю тебя)[\s,!.:]+)+", re.I)
_EXPLICIT = re.compile(
    r"^(?:меня\s+зовут|зовут\s+меня|мо[её]\s+имя|имя\s+мо[её]|"
    r"зови(?:те)?\s+меня|называй\s+меня|можешь\s+(?:звать|называть)\s+меня)"
    r"(?:\s*[:=]\s*|\s+)", re.I)
# These words denote states, roles or grammar, not a short introduction.
# Explicit naming phrases accept unfamiliar names and nicknames in any alphabet.
_NOT_NAME = set("""
    не как кто что почему никто нигде никак домой гулять кушать есть спать
    я ты он она мы вы они а и но мой моя мое моё твой твоя очень привет
    на в во из с со за по к ко от до у о об при без для через
    тут там здесь туда оттуда дома назад рядом сегодня завтра вчера сейчас
    потом уже еще ещё тоже только просто вообще вроде наверное может
    устал устала устали рад рада занят занята готов готова согласен согласна
    заболел заболела проспал проспала опоздал опоздала пришел пришёл пришла
    вернулся вернулась забыл забыла закончил закончила понял поняла
    студент студентка школьник школьница программист разработчик человек бот
    робот новичок учитель врач инженер спортсмен дизайнер друг подруга
    один одна первый первая второй вторая последний последняя лучший лучшая
    норм нормально отлично хорошо плохо грустный грустная голодный голодная
    хочу могу буду был была есть люблю работаю учусь думаю знаю читаю слушаю
    играю иду еду сижу лежу жду сплю ем пью пишу смотрю делаю готовлю понимаю
    выиграл выиграла проиграл проиграла сдал сдала смогу успею попробую
    усталый уставший веселый весёлый скучный счастлив счастливый уверен уверена
    обиделся обиделась расстроился расстроилась ошибся ошиблась серьезно серьёзно
    болею отдыхаю опаздываю скучаю молодец печальный печальная
    редко необычно состоит тебе вам мне нам известно неизвестно ужинать обедать
    задумчивый задумчивая грустный грустная счастливый счастливая смешной смешная
    печальный печальная сонный сонная уставшая довольный довольная занятый занятая
    синий синяя красный красная хороший хорошая плохой плохая голодная одинокий одинокая
""".split())


def _read_name_token(value):
    if not value:
        return None
    quotes = {'«': '»', '"': '"', '“': '”', "'": "'"}
    if value[0] in quotes:
        closing = value.find(quotes[value[0]], 1)
        if closing < 0:
            return None
        return value[1:closing].strip(), value[closing + 1:]
    position = 0
    start = position
    if position < len(value) and value[position] == '@':
        position += 1
    while position < len(value):
        char = value[position]
        if unicodedata.category(char)[0] in ('L', 'M', 'N') or char in "_-'’":
            position += 1
        else:
            break
    name = value[start:position].rstrip("'")
    if position < len(value) and value[position] in '»"”':
        position += 1
    return name, value[position:]


def _name_value(value):
    parsed = _read_name_token(value)
    if parsed is None:
        return None
    name, remainder = parsed
    if name.casefold().replace("ё", "е") in _NOT_NAME:
        return None
    # Proper compound names and surnames can contain several Unicode words.
    for _ in range(3):
        if not remainder or not remainder[0].isspace():
            break
        component = _read_name_token(remainder.lstrip())
        if not component or not component[0]:
            break
        word = component[0]
        if word.casefold().replace("ё", "е") in _NOT_NAME:
            break
        if not (word[0].isupper() or (word[0].isalpha() and not word[0].islower())):
            break
        name += ' ' + word
        remainder = component[1]
    # Never accept just the prefix of a token or a purely numeric label.
    if remainder and not (remainder[0].isspace() or remainder[0] in ",.!?;:)"):
        return None
    if not 1 <= len(name) <= 60 or not any(c.isalpha() for c in name):
        return None
    if any(unicodedata.category(c)[0] not in ('L', 'M', 'N') and c not in " _-'’@" for c in name):
        return None
    if name.casefold().replace("ё", "е") in _NOT_NAME:
        return None
    if name.islower() and not name.startswith("@"):
        name = name[0].upper() + name[1:]
    return name, remainder


def parse_introduction(text):
    """Return (name, remaining text) only for a direct first-person statement.

    Quotes about somebody else, questions and a negated name never update memory.
    Names are Unicode text, so this works for unseen names without a name list.
    """
    text = unicodedata.normalize("NFC", text).strip()
    text = _PREFACE.sub("", text)
    explicit = _EXPLICIT.match(text)
    short = re.match(r"^я\s+", text, re.I) if explicit is None else None
    if not explicit and not short:
        return None
    tail = text[(explicit or short).end():].lstrip()
    negative = re.match(r"не\s+", tail, re.I)
    if negative:
        old_name = _read_name_token(tail[negative.end():])
        if not old_name or not old_name[0]:
            return None
        correction = re.match(r"\s*,?\s+(?:а\s+|я\s+|(?=меня\s+зовут|зовут\s+меня|мо[её]\s+имя))", old_name[1], re.I)
        if correction is None:
            return None
        tail = old_name[1][correction.end():]
        repeated = _EXPLICIT.match(tail)
        if repeated:
            tail = tail[repeated.end():]
    parsed = _name_value(tail)
    if parsed is None:
        return None
    name, remainder = parsed
    if remainder.lstrip().startswith("?"):
        return None
    if re.match(r"^\s*или\b|^\s*,?\s*(?:да|верно|правда|правильно|не так ли)\s*\?", remainder, re.I):
        return None
    # A descriptive sentence such as 'моё имя редко кому знакомо' isn't naming.
    if explicit and remainder.strip(" ,.!;:"):
        if not re.match(r"^\s*[,!.;]|^\s+(?:а|и|я|мне)\s+", remainder):
            return None
    if short:
        raw = _read_name_token(tail)[0]
        # Common lowercase verb endings protect ordinary 'я ...' turns.
        # Title-case unfamiliar names still work, and explicit forms need no dictionary.
        if (raw.islower() or raw.isupper()) and re.search(
            r"(?:аю|яю|ую|ею|юсь|ился|илась|лся|лась|ешь|ете|ать|ять|ить)$", raw.casefold()):
            return None
    if short and remainder.strip(" ,.!;:"):
        # Keep the shorthand narrow: a following clause must have a clear boundary.
        if not re.match(r"^\s*[,!.;]|^\s+(?:а|и)\s+", remainder):
            return None
    return name, remainder.strip(" ,.!;:")
