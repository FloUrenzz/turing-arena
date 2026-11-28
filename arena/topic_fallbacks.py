"""Short, topic-aware admissions for questions the main pipeline cannot answer.

Call this only after rules and successful corpus retrieval. These patterns
recognize a few explicit requests, not every occurrence of a subject name.
They provide no scientific, medical or philosophical claims.
"""

import re


CASUAL_FALLBACK = 'Рассказывай, я слушаю'

TOPIC_FOLLOWUPS = {
    'Волнение и общение': 'Хочешь рассказать, что случилось?',
    'Встречи': 'А как всё вышло со встречей?',
    'Дела и покупки': 'А как у тебя с этим продвигается?',
    'Домашние дела': 'А что дома осталось сделать?',
    'Домашние задания': 'А что именно задали?',
    'Домашняя еда': 'А что вы обычно дома готовите?',
    'Дорога и транспорт': 'А ты часто этим маршрутом ездишь?',
    'Занятия и материалы': 'А это для занятия или сам разбираешься?',
    'Игры': 'А во что сейчас играешь?',
    'Кафе и обед': 'А куда обычно ходишь поесть?',
    'Книги': 'А что сейчас читаешь?',
    'Компьютер и файлы': 'А что у тебя на экране сейчас?',
    'Музыка': 'А что обычно слушаешь?',
    'Одежда и вещи': 'А какую вещь в итоге выбрал?',
    'Переписка': 'А что тебе написали?',
    'Планы и встречи': 'А какие у тебя сейчас планы?',
    'Погода и день': 'А у вас сейчас какая погода?',
    'Подготовка к выступлению': 'А ты уже успел порепетировать?',
    'Подготовка к проверкам': 'А как готовишься к экзамену?',
    'Поездки': 'А куда собираешься ехать?',
    'Понимание учебных тем': 'А на какой теме ты сейчас?',
    'Порядок дома': 'А что хочешь разобрать в первую очередь?',
    'Прогулка и район': 'А где обычно гуляешь?',
    'Прогулки в поездках': 'А куда хочешь сходить в поездке?',
    'Продукты и магазин': 'А что хотел взять в магазине?',
    'Работа над проектом': 'А на каком этапе у вас проект?',
    'Рабочий день': 'А как у тебя сегодня на работе?',
    'Разговор с друзьями': 'А что было дальше?',
    'Распорядок': 'А у тебя сегодня ещё есть планы?',
    'Спорт': 'А чем сейчас занимаешься из спорта?',
    'Творческие проекты': 'А что за работа у тебя сейчас?',
    'Техника в быту': 'А как эта штука себя ведёт?',
    'Фильмы': 'А какой фильм или сериал имеешь в виду?',
    'Хобби': 'А давно этим увлекаешься?',
    'Программирование': 'А на каком языке пишешь?',
}


_PRODUCT = re.compile(
    r'\b(?:шампун\w*|крем\w*|гел[ьяею]\w*|мыл[оауе]\w*|косметик\w*|'
    r'дезодорант\w*|лосьон\w*|зубн\w*\s+паст\w*|моющ\w*\s+средств\w*|'
    r'чистящ\w*\s+средств\w*|средств[оауы]\b|порошк\w*|порошок|'
    r'shampoo|cream|soap|cosmetics?|deodorant|lotion|toothpaste|detergent|cleaner)\b')
_COMPOSITION = re.compile(
    r'\b(?:состав(?:а|е|у|ом)?|ингредиент\w*|компонент\w*|'
    r'из\s+чего\s+(?:состоит|сделан\w*)|ingredients?|composition|made\s+(?:of|from))\b')
_COMPOSITION_SHORT = re.compile(
    r'^(?:состав(?:а|е|у|ом)?|ингредиент\w*|компонент\w*|'
    r'ingredients?|composition)\b')
_REQUEST_START = re.compile(
    r'^(?:что|почему|зачем|как|какой|какая|какое|какие|кто|где|когда|'
    r'сколько|из\s+чего|в\s+чем|чем|существует\s+ли|есть\s+ли|'
    r'объясни(?:ть)?|расскажи|рассказать|поясни(?:ть)?|разбери|разобрать|'
    r'назови|назвать|подскажи|подсказать|опиши|описать|напиши|написать|'
    r'перечисли(?:ть)?|сравни(?:ть)?|реши(?:ть)?|докажи|доказать|найди|найти|'
    r'ты\s+знаешь|знаешь\s+ли|'
    r'what|why|how|which|who|where|when|does|do|is|are|'
    r'explain|describe|tell|list|compare|solve|prove)\b')
_PREFACE = re.compile(
    r'^(?:(?:а|ну|слушай|пожалуйста|плиз|скажи|можешь|помоги|'
    r'please|can\s+you|could\s+you)\s*[,!:]?\s+)+')
_ACADEMIC = re.compile(
    r'\b(?:физик\w*|хими(?:я|и|ю|ей)|биолог\w*|математик\w*|алгебр\w*|'
    r'геометр\w*|астроном\w*|геолог\w*|географ\w*|термодинамик\w*|'
    r'тригонометр\w*|сопромат\w*|энтроп\w*|теорем\w*|'
    r'электродинамик\w*|квант\w*|относительност\w*|фотосинтез\w*|'
    r'генетик\w*|орбитал\w*|электрон\w*|протон\w*|нейтрон\w*|'
    r'изотоп\w*|атом\w*|молекул\w*|интеграл\w*|дифференциал\w*|'
    r'physics|chemistry|biology|mathematics|algebra|geometry|astronomy|'
    r'geology|geography|thermodynamics|quantum|relativity|photosynthesis|'
    r'genetics|electrons?|protons?|neutrons?|isotopes?|atoms?|molecules?|integrals?)\b')
_SCHOOL_SOCIAL = re.compile(
    r'\b(?:экзамен\w*|контрольн\w*|зачет\w*|учител\w*|преподавател\w*|'
    r'одноклассник\w*|оценк\w*|расписан\w*|кабинет\w*|команд\w*|'
    r'exams?|teachers?|professors?|grades?|classmates?|timetable|team)\b')
_PHILOSOPHY = re.compile(
    r'\b(?:философ\w*|смысл\w*\s+(?:человеческ\w*\s+)?(?:жизни|существования)|'
    r'свобод\w*\s+воли|объективн\w*\s+истин\w*|'
    r'что\s+(?:есть|такое)\s+истина|зачем\s+(?:мы|люди)\s+жив\w*|'
    r'philosoph\w*|meaning\s+of\s+(?:human\s+)?life|'
    r'free\s+will|objective\s+truth|why\s+(?:do\s+)?(?:we|people)\s+live)\b')
_PERSONAL_DISTRESS = re.compile(
    r'\b(?:мне|меня|моей|мою|моя|себя|собой|не\s+хочу\s+жить|'
    r'не\s+вижу\s+смысла|my\s+life|myself|want\s+to\s+die|'
    r'don.?t\s+want\s+to\s+live)\b')

_RESPONSES = {
    'composition': 'я не изучаю составы, тут не подскажу',
    'academic': 'я в этом предмете не особо разбираюсь',
    'philosophy': 'я над таким особо не задумывался',
}


def topic_fallback(question):
    """Return {'text': ..., 'topic': ...} or None for an unsupported mention.

    Responses always use Russian, independently of the query spelling.
    Only the caller knows whether a higher-priority rule already has an answer.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        return None
    text = ' '.join(question.casefold().replace('ё', 'е').split())
    focus = _PREFACE.sub('', text)
    request = bool(_REQUEST_START.search(focus) or '?' in focus)
    topic = None
    direct_composition = bool(re.match(r'^(?:(?:какой|химический)\s+)?состав\b|^из\s+чего\s+(?:состоит|сделан\w*)\b|^ingredients\s+of\b', focus))
    if (_PRODUCT.search(text) or direct_composition) and _COMPOSITION.search(text) and (
            request or _COMPOSITION_SHORT.search(focus)):
        # "Средство общения" and "состав команды" are not product ingredients.
        if not re.search(r'\b(?:средств\w*\s+(?:общения|передвижения|обучения)|'
                         r'команд\w*|групп\w*|поезд\w*|сборн\w*|жюри|комисси\w*|кафедр\w*)\b', text):
            topic = 'composition'
    if topic is None and request and _PHILOSOPHY.search(text):
        # Do not answer a personal distress statement with a casual dismissal.
        if not _PERSONAL_DISTRESS.search(text) and not _SCHOOL_SOCIAL.search(text):
            topic = 'philosophy'
    if topic is None and request and _ACADEMIC.search(text):
        if not _SCHOOL_SOCIAL.search(text) and not re.search(
                r'\b(?:фильм\w*|игр\w*|сериал\w*|учусь|сдал\w*|'
                r'как\s+дела|movie|game|series|passed|studying)\b', text):
            topic = 'academic'
    if topic is None:
        return None
    return {'text': _RESPONSES[topic], 'topic': topic}
