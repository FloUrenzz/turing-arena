"""Short conversational continuations, bounded by the current dialogue turn."""

import re
import unicodedata
from .paraphrases import phrase_features


_EXAM_SUCCESS = {phrase_features(prefix + 'сдал экзамен')
                 for prefix in ('', 'я ', 'сегодня ', 'я сегодня ', 'вчера ', 'наконец ')}
_EXAM_FAILURE = {phrase_features(prefix + action + ' экзамен')
                 for prefix in ('', 'я ', 'сегодня ', 'я сегодня ', 'вчера ')
                 for action in ('не сдал', 'завалил')}


def _normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е')
    text = re.sub(r'\bнич[ео]\b', 'ничего', text)
    text = re.sub(r'\bч[ео]\b', 'что', text)
    text = text.replace(',', ' ')
    text = ' '.join(text.strip(' .!?').split())
    # Correct only a complete, recognizable activity question. Do not fuzzily
    # rewrite words in questions about tomorrow, negations or another person.
    if re.fullmatch(r'(?:а )?что (?:ты )?(?:(?:сейчас|щас|ща) )?'
                    r'(?:делаешь|делаеш|делашь|далешь|делаш|делаешъ)', text):
        return 'что сейчас делаешь' if re.search(r'\b(?:сейчас|щас|ща)\b', text) else 'что делаешь'
    return text


def _questions(text):
    return {_normalize(part) for part in re.findall(r'[^.!?]*\?', text)}


def _startup_activity(text):
    """A complete first-person activity statement, including a comparison prefix."""
    core = re.sub(r'^(?:(?:да|ну|я|сейчас|щас|просто|тоже|как и ты|так же как ты)\s+)*', '', text)
    project = r'(?:(?:новый|свой) )?стартап|(?:(?:новые|свои) )?стартапы'
    ideas = r'(?:(?:новую|свою) )?идею для стартапа|(?:(?:новые|свои) )?идеи для стартап(?:а|ов)'
    objects = rf'(?:{project}|{ideas})'
    return bool(re.fullmatch(
        rf'(?:придумываю|обдумываю|продумываю) {objects}|'
        rf'{objects} (?:придумываю|обдумываю|продумываю)|'
        r'думаю над (?:(?:новым|своим) стартапом|идеей (?:для )?стартапа)|'
        r'ищу (?:новые )?идеи для стартап(?:а|ов)', core))


def _short_answer_kind(text):
    """Recognize the complete answer half, never just a convenient substring."""
    text = re.sub(r'^(?:(?:да|ну|я|тоже|просто|сейчас|вообще|вроде)\s+|у меня\s+)*', '', text)
    if re.fullmatch(r'ничем(?: особенным)?|ничем не (?:занят|занята|занимаюсь)|'
                    r'ничего(?: особенного| особого)?|все так же', text):
        return 'idle'
    if re.fullmatch(r'норм|нормас|нормально|хорошо|отлично|неплохо|в порядке|спокойно|'
                    r'пойдет|терпимо|более[- ]менее|потихоньку|как обычно|все нормально', text):
        return 'mood'
    if re.fullmatch(r'(?:мне )?(?:плохо|так себе|не очень|грустно|неважно)', text):
        return 'mood_bad'
    if _startup_activity(text):
        return 'activity'
    if re.fullmatch(r'сижу(?: дома)?|дома сижу|отдыхаю(?: дома)?|валяюсь(?: дома)?|'
                    r'работаю|учусь|гуляю|ем|обедаю|ужинаю|завтракаю|'
                    r'смотрю (?:фильм|кино|сериал)|слушаю музыку|читаю книгу|'
                    r'делаю (?:домашку|уроки)|готовлюсь к экзамену', text):
        return 'activity'
    return None


def _reciprocal_kind(text):
    """Classify a whole follow-up question, preserving qualifiers and negation."""
    core = re.sub(r'^(?:(?:а|ну|и|ты|сам|сама)\s+){0,4}', '', text)
    core = _normalize(core)
    if re.fullmatch(r'что (?:сейчас )?делаешь|чем (?:ты )?(?:сейчас )?(?:занят|занята|занимаешься)', core):
        return 'activity'
    if re.fullmatch(r'как (?:у тебя )?(?:дела|настроение)|как (?:ты|сам|сама)|'
                    r'как у тебя|у тебя как(?: дела| настроение)?', core):
        return 'mood'
    if core == 'как' and re.fullmatch(r'(?:(?:а|ну|и) )?(?:ты|сам|сама) как', text):
        return 'mood'
    if re.fullmatch(r'(?:(?:а|ну|и) )?(?:ты|сам|сама|у тебя)', text):
        return 'elliptic'
    return None


def _answer_and_question(text):
    # A comma is optional in chat. Try word boundaries, accepting both halves
    # only when their complete meanings are recognized independently.
    for boundary in re.finditer(r'\s+', text):
        head = text[:boundary.start()].rstrip(' .!?;')
        tail = text[boundary.end():]
        answer_kind = _short_answer_kind(head)
        if answer_kind is not None:
            question_kind = _reciprocal_kind(tail)
            if question_kind is not None:
                return answer_kind, question_kind
    return None


def conversational_reply(question, state):
    """Return a confident casual reply or None, without changing conversation state.

    Full utterance matches keep these reactions away from unrelated factual,
    mathematical and technical requests. Elliptical answers use the last turn.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > 240:
        return None
    if '\n' in question or any(char in question for char in '«»"'):
        return None
    text = _normalize(question)
    history = state.get('history', [])
    last = history[-1] if history else {}
    bot = _normalize(last.get('text', ''))
    previous_user = _normalize(last.get('question', ''))
    recent_questions = set().union(*(_questions(turn.get('text', '')) for turn in history[-3:])) if history else set()

    def reply(topic, *choices):
        for choice in choices:
            if not (_questions(choice) & recent_questions):
                return {'text': choice, 'topic': 'smalltalk:' + topic}
        return {'text': 'Оке, понял', 'topic': 'smalltalk:' + topic}

    def matches(pattern):
        return re.fullmatch(pattern, text) is not None

    activity_question = bool(re.search(r'что (?:сейчас )?делаешь|чем (?:сейчас )?(?:занят|занимаешься)|ничего особенного', bot))
    activity_question = activity_question or (bool(re.search(r'а ты|сам как', bot)) and bool(re.fullmatch(
        r'(?:а )?(?:что (?:сейчас )?делаешь|чем (?:сейчас )?(?:занят|занимаешься))', previous_user)))
    mood_question = bool(re.search(r'как (?:у тебя )?(?:дела|день|настроение)|сам как|ты как', bot))
    mood_question = mood_question or (bot.endswith('а ты') and bool(re.search(r'как (?:дела|ты|сам)', previous_user)))
    day_question = bool(re.search(r'как день|день прошел|день проходит', bot))
    exam_result_question = bool(re.search(r'как прошло|как прошел|как в итоге', bot)) and 'экзамен' in previous_user

    combined = _answer_and_question(text)
    if combined is not None:
        answer_kind, question_kind = combined
        if question_kind == 'elliptic':
            if activity_question or answer_kind == 'activity':
                question_kind = 'activity'
            elif mood_question or day_question or answer_kind in ('mood', 'mood_bad'):
                question_kind = 'mood'
            elif answer_kind == 'idle':
                question_kind = 'activity'
        if answer_kind == 'mood_bad':
            return reply('mood_bad', 'Я тут, с тобой общаюсь. А у тебя что случилось?',
                         'Я с тобой. Можешь рассказать, что случилось')
        if question_kind == 'activity':
            return reply('activity', 'Да тоже ничего особенного, с тобой общаюсь'
                         if answer_kind == 'idle' else 'Сейчас просто общаюсь с тобой')
        if question_kind == 'mood':
            return reply('mood', 'Да нормально, общаемся вот')

    if '?' not in question and _startup_activity(text):
        return reply('startup', 'Есть уже какая-нибудь идея?', 'О, а что за идея?')

    # Common opening questions are useful even without a matching corpus row.
    if matches(r'(?:привет|приветик|салам|салем|ку|хай)(?: (?:как (?:дела|ты|сам)|что как))?'):
        if text.startswith(('салам', 'салем')):
            return reply('mood', 'Салам, всё чётко, сам как?', 'Салам, я тут')
        if text.startswith('ку'):
            return reply('mood', 'Ку, норм, ты как?', 'Ку, я тут')
        return reply('mood', 'Привет, норм, сам как?', 'Привет, я тут')
    if matches(r'(?:а )?(?:что (?:сейчас )?делаешь|чем (?:сейчас )?(?:занят|занимаешься))'):
        return reply('activity', 'Да ничё особенного. А ты?', 'Сейчас просто общаюсь с тобой')
    if matches(r'(?:а )?(?:как (?:у тебя )?дела|как сам|ты как)'):
        return reply('mood', 'Норм, сам как?', 'Да нормально')
    explicit_question = _reciprocal_kind(text)
    if explicit_question == 'activity':
        return reply('activity', 'Сейчас просто общаюсь с тобой')
    if explicit_question == 'mood':
        return reply('mood', 'Да нормально, общаемся вот')

    if matches(r'(?:да |ну |я |тоже |также |особо )*(?:ничего(?: особенного| особого)?|ничем(?: особенным)?|ничем не занят|ничем не занимаюсь|все так же)'):
        if activity_question or mood_question:
            return reply('day', 'Понял. Как день прошёл?', 'Оке. Что планируешь дальше?', 'Оке, можем просто поболтать')
        if matches(r'(?:да |ну |я |тоже )*(?:ничем не занят|ничем не занимаюсь)'):
            return reply('free_time', 'Хочешь просто поболтать?', 'Оке, я тут')
        return None

    if matches(r'(?:да |ну |все |у меня |тоже |вроде )*(?:пойдет|терпимо|более-менее|более менее)'):
        if mood_question or day_question:
            return reply('activity', 'Понял. Чем занимаешься?', 'Оке, понял')
        return None

    if matches(r'(?:да |ну |все |у меня |тоже |вроде )*(?:норм|нормас|нормально|хорошо|отлично|неплохо|в порядке|спокойно)'):
        if exam_result_question:
            return reply('exam_subject', 'О, имба. Что за предметы были?', 'О, хорошо')
        if day_question:
            return reply('day_detail', 'О, хорошо. Что-нибудь интересное было?', 'О, хорошо')
        if mood_question:
            return reply('activity', 'О, хорошо. Чем занимаешься?', 'О, хорошо')
        if (last.get('topic') or '').startswith('smalltalk:'):
            return reply('ack', 'Оке, понял')
        return None
    if matches(r'(?:да |ну |у меня |что-то )*(?:не очень|так себе|плохо|не норм|не нормально|не хорошо|неважно)'):
        if mood_question or day_question:
            return reply('mood_bad', 'Эх. Что случилось?', 'Понимаю. Хочешь рассказать?', 'Я тут, можешь рассказать')
        return None
    if mood_question and matches(r'(?:да |ну )?(?:как обычно|все как обычно|потихоньку|ничего нового)'):
        return reply('day', 'Понял. Что планируешь дальше?', 'Оке, обычный день')

    if matches(r'(?:а )?(?:ты|у тебя|сам|тебя как)'):
        if activity_question or last.get('topic') in ('smalltalk:activity', 'smalltalk:free_time'):
            return reply('activity', 'Да тоже ничего особенного, с тобой общаюсь')
        if mood_question or day_question or last.get('topic') in ('smalltalk:mood', 'smalltalk:day'):
            return reply('mood', 'Да нормально, общаемся вот')
        if last.get('topic') == 'smalltalk:day_detail' or 'что-нибудь интересное было' in bot:
            return reply('day_detail', 'Да ничего особенного, с тобой общаюсь')
        if last.get('topic') == 'smalltalk:movie' or re.search(r'как тебе (?:пока|фильм|кино|сериал)', bot):
            return reply('movie', 'Я сейчас с тобой общаюсь')
        if last.get('topic') == 'smalltalk:music' or re.search(r'что за музыка|какой.*трек|есть любимый трек', bot):
            return reply('music', 'Сейчас ничего не слушаю, общаюсь с тобой')
        return None

    if matches(r'(?:да |я |просто |тоже |сейчас )*(?:сижу дома|дома сижу|ничего просто сижу)'):
        return reply('home', 'Оке. Как день проходит?', 'Оке, я тут')
    if matches(r'(?:да |я |просто |тоже |сейчас )*(?:отдыхаю|валяюсь дома|отдыхаю дома)'):
        return reply('rest', 'Оке, отдыхаешь. Что обычно включаешь в такие моменты?', 'Оке, можно никуда не спешить')
    if matches(r'(?:мне |что-то |просто |да )*(?:скучно|скучновато|нечем заняться)'):
        return reply('bored', 'Хочешь поболтать или придумать, чем заняться?', 'Можем просто поболтать', 'Я тут')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:смотрю (?:фильм|кино|сериал)|фильм смотрю|сериал смотрю)'):
        return reply('movie', 'А что смотришь?', 'Как тебе пока?')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:слушаю музыку|музыку слушаю|слушаю плейлист)'):
        return reply('music', 'А что за музыка?', 'Какой трек сейчас включён?')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:гуляю|вышел погулять|вышла погулять|иду гулять)'):
        return reply('walk', 'О, как там на улице?', 'Оке, приятной прогулки')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:учу уроки|делаю домашку|делаю домашнее задание)'):
        return reply('homework', 'По какому предмету?', 'Много ещё осталось?')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:готовлюсь к экзамену|учу билеты|повторяю билеты)'):
        return reply('exam', 'По какому предмету экзамен?', 'Когда сдавать?')
    features = phrase_features(question)
    if features in _EXAM_SUCCESS or ('?' not in question and matches(r'(?:я |сегодня |наконец |наконец-то )*(?:сдал|сдала) экзамен')):
        return reply('exam_result', 'О, имба. Как прошло?', 'А что за предмет был?')
    if features in _EXAM_FAILURE or ('?' not in question and matches(r'(?:я |походу |кажется |сегодня )*(?:завалил|завалила|не сдал|не сдала) экзамен')):
        return reply('exam_result', 'Обидненько. А результаты уже вышли?', 'Эх. Может, ещё не всё ясно')
    if matches(r'(?:я |просто |очень |сегодня )*(?:устал|устала|выдохся|выдохлась)'):
        return reply('tired', 'Понимаю. Тяжёлый день был?', 'Можно немного передохнуть')
    if matches(r'(?:сейчас |вообще |мне |просто )*ничего не хочется'):
        return reply('tired', 'Можно пока ничего не делать, просто передохнуть')
    if matches(r'(?:у меня |сегодня у меня |сегодня |завтра у меня |завтра )выходной'):
        return reply('day_off', 'О, каеф. Уже придумал, чем займёшься?', 'Можно спокойно отдохнуть')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:жду друга|жду подругу|жду друзей)'):
        return reply('meeting', 'Давно ждёшь?', 'Надеюсь, скоро подойдут')
    if matches(r'(?:я |сейчас |просто |тоже )*(?:ем|обедаю|ужинаю|завтракаю)'):
        return reply('food', 'Приятного аппетита', 'Оке, приятного')
    if matches(r'(?:я |сейчас |уже )*(?:иду спать|ложусь спать|собираюсь спать)'):
        return reply('goodnight', 'Спокойной ночи', 'Хорошего сна')

    # Short answers to particular follow-up questions, not arbitrary yes/no facts.
    positive = matches(r'(?:да|ага|угу|кнш|конечно|давай|да давай|хочу|можно|почему бы и нет)')
    negative = matches(r'(?:нет|неа|нее|не хочу|не надо|не сейчас|пока нет|пока не хочу)')
    if positive or negative:
        if last.get('topic') == 'smalltalk:startup' and 'есть уже какая-нибудь идея' in bot:
            return reply('startup', 'О, а что за идея?' if positive else 'Оке, можно пока просто подумать')
        if re.search(r'хочешь.*(?:поболтать|рассказать)|можем.*поболтать', bot):
            if negative:
                return reply('pause', 'Оке, как захочешь')
            return reply('conversation', 'Давай. О чём хочешь поговорить?', 'Рассказывай, я слушаю')
        if re.search(r'что-нибудь интересное было|интересное.*было', bot):
            return reply('day_detail', 'Расскажи, что запомнилось' if positive else 'Понял, обычный день')
        if re.search(r'понравил(?:ся|ась|ось)|как тебе (?:фильм|кино|сериал)', bot):
            return reply('movie', 'А что больше всего понравилось?' if positive else 'А что не зашло?')
        if re.search(r'результаты.*(?:вышли|есть|пришли)', bot):
            return reply('exam', 'И как в итоге?' if positive else 'Тогда пока рано себя накручивать')
        if re.search(r'будильник ставил', bot):
            return reply('sleep', 'Не услышал его?' if positive else 'Оке, на завтра можно поставить')
        if re.search(r'тяжелый день был', bot):
            return reply('tired', 'Понимаю, можно немного выдохнуть' if positive else 'Бывает, усталость и без суеты приходит')
        if re.search(r'сложные задания были', bot):
            return reply('exam', 'Что было самым сложным?' if positive else 'О, хорошо, что без сложностей')
        if re.search(r'много еще осталось', bot):
            return reply('progress', 'Тогда можно по одному, без спешки' if positive else 'О, уже почти закончил')
        if re.search(r'есть любимый трек', bot):
            return reply('music', 'Как называется?' if positive else 'Понял, одного любимого нет')
        if re.search(r'друг.*(?:пришел|подошел)|уже встретились', bot):
            return reply('meeting', 'О, дождался' if positive else 'Оке. Он сказал, когда будет?')
        return None

    if re.search(r'(?:какой|какому|что за).*предмет|какой экзамен', bot):
        if matches(r'(?:по )?(?:математика|математике|алгебра|алгебре|геометрия|геометрии|физика|физике|химия|химии|биология|биологии|история|истории|информатика|информатике|английский|английскому|русский|русскому|казахский|казахскому)(?: язык| языку)?'):
            return reply('exam_subject', 'Сложные задания были?' if re.search(r'были|был|сдал', bot + ' ' + previous_user) else 'А какая тема сложнее всего?')
    if re.search(r'какая тема сложнее|что было самым сложным', bot):
        if matches(r'(?:больше всего )?(?:интегралы|производные|тригонометрия|геометрия|задачи|формулы|теоремы|грамматика|даты)'):
            return reply('study_detail', 'А что именно в этой теме не получается?')
    if re.search(r'много еще осталось', bot):
        if matches(r'(?:да |ну )?(?:немного|чуть-чуть|совсем немного|почти все|пара заданий|одно задание|один билет|два билета)'):
            return reply('progress', 'О, уже почти закончил')
        if matches(r'(?:да |ну )?(?:много|еще много|довольно много|почти все еще впереди)'):
            return reply('progress', 'Тогда можно по одному, без спешки')
    if re.search(r'когда сдавать|когда экзамен', bot):
        if matches(r'(?:уже |только )?(?:завтра|послезавтра|через неделю|на следующей неделе|в понедельник|во вторник|в среду|в четверг|в пятницу|в субботу|в воскресенье)'):
            return reply('exam_time', 'А сколько ещё осталось повторить?')
    if re.search(r'давно ждешь|сколько уже ждешь', bot):
        if matches(r'(?:уже |около |примерно )?(?:\d{1,3} минут|пять минут|десять минут|пятнадцать минут|полчаса|час|недолго|давно)'):
            return reply('meeting', 'Он написал, когда подойдёт?', 'Оке, надеюсь, скоро встретитесь')
    if re.search(r'как (?:тебе )?(?:фильм|кино|сериал)|как тебе пока', bot):
        if matches(r'(?:да |пока )?(?:нравится|интересно|очень интересно|зашло|классный|классно|так себе|скучно|не нравится|не зашло)'):
            return reply('movie', 'А что не зашло?' if re.search(r'так себе|скучно|не ', text) else 'О, хорошо. Что зацепило?')
    if re.search(r'что смотришь|какой фильм|какой сериал', bot):
        if matches(r'(?:смотрю )?(?:комедию|боевик|драму|детектив|ужастик|фантастику|аниме|документалку|сериал|комедия)'):
            return reply('movie', 'Как тебе пока?', 'Надеюсь, зайдёт')
    if re.search(r'что.*(?:включаешь|музыка)|какой.*трек', bot):
        if matches(r'(?:да |обычно |слушаю )?(?:разную|всякую|все подряд|что попадется|по настроению)'):
            return reply('music', 'А что сейчас играет?')
        if matches(r'(?:обычно |сейчас |просто )?(?:рок|рэп|поп|джаз|электронику|попсу|лоуфай|спокойную музыку|ничего не включаю|тишина|в тишине)'):
            return reply('music', 'Оке, иногда тишина тоже в тему' if re.search(r'тишин|ничего', text) else 'А есть любимый трек?')
    if 'что сейчас играет' in bot and matches(r'(?:да |сейчас )?(?:ничего|тишина|ничего не играет)'):
        return reply('music', 'Оке, сейчас без музыки')
    if re.search(r'придумал.*чем займешься|что планируешь', bot):
        if matches(r'(?:да |ну |пока )?(?:не знаю|не придумал|ничего не планировал|без планов|планов нет)'):
            return reply('free_time', 'Можно пока никуда не спешить')
    if last.get('topic') == 'smalltalk:tired' and matches(r'(?:а )?(?:что посоветуешь|что делать|как отдохнуть)'):
        return reply('tired', 'Можно ненадолго отложить дела и посидеть в тишине')

    if matches(r'(?:спасибо|спс|благодарю|спасибо тебе|большое спасибо|спасибо большое)'):
        return reply('thanks', 'Да не за что')
    if matches(r'(?:ну |да )?(?:понятно|понял|поняла|ясно|оке|окей|ок|хорошо понял|а понял|а понятно|ладно|ладно понял)'):
        return reply('ack', 'Оке')
    if matches(r'(?:пока|до связи|увидимся|спишемся|ладно пока)'):
        return reply('goodbye', 'Давай, до связи')
    return None
