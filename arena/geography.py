"""Small factual relations with interchangeable word order, not keyword answers."""

import re


_FORMS = {
    'almaty': 'алматы алмата алма-ата алмаата',
    'astana': 'астана астаны астане астану',
    'kazakhstan': 'казахстан казахстана казахстане казахстанский казахстанская казахстанской рк',
    'istanbul': 'стамбул стамбула стамбуле',
    'ankara': 'анкара анкары анкаре анкару',
    'turkey': 'турция турции турцию турецкая турецкий',
    'capital': 'столица столицы столицей столицу столичная столичный',
    'baikal': 'байкал байкала байкале',
    'sea': 'море морем моря',
    'lake': 'озеро озером озера',
    'antarctica': 'антарктида антарктиды антарктиде антарктиду',
    'north': 'север севере северном северное',
    'south': 'юг юге южном южное',
    'hemisphere': 'полушарие полушарии',
    'taiwan': 'тайвань тайваня тайване тайванем',
    'china': 'китай китая китае китаю китайский китайская китайским',
    'city': 'город городом города',
    'island': 'остров островом острова',
    'country': 'страна страной страны государство государством государства',
    'independent': 'независимая независимый независимое независимым независимой самостоятельная самостоятельным самостоятельное отдельная суверенное суверенная',
    'part': 'часть частью принадлежит принадлежать',
    'status': 'статус статусом',
    'past': 'раньше ранее бывшая бывшей была был являлась являлся',
}
_ALIASES = {word: meaning for meaning, forms in _FORMS.items() for word in forms.split()}
_FILLERS = set('а ну типа слушай скажи это же вообще там сейчас да ли разве правда является '
               'считается получается ведь что такое кто какая какой какое какие у в на или '
               'как тогда теперь все таки правильно понял понимаю я получается имеется разве '
               'серьезно знаешь пожалуйста ответь по факту находится расположен расположена'.split())
_NEGATIVE = {'не', 'нет'}


def geography_reply(question):
    if not isinstance(question, str) or len(question) > 220 or re.search(r'[«»"\n;\d]', question):
        return None
    text = question.casefold().replace('ё', 'е')
    words = re.findall(r'[^\W\d_]+(?:-[^\W\d_]+)?', text)
    if not words or any(word not in _ALIASES and word not in _FILLERS and word not in _NEGATIVE for word in words):
        return None
    # One relation at a time. Never silently answer the first of two questions.
    if '?' in text.rstrip(' ?!.,') or re.search(r'\b(?:почему|когда|зачем|если|но|и)\b', text):
        return None
    meanings = {_ALIASES[word] for word in words if word in _ALIASES}
    negative = bool(set(words) & _NEGATIVE)

    def answer(rule, text):
        return {'text': text, 'topic': 'geography:' + rule, 'rule': rule}

    kz_entities = {'almaty', 'astana', 'kazakhstan'}
    tr_entities = {'istanbul', 'ankara', 'turkey'}
    if 'capital' in meanings and meanings & kz_entities and not meanings & tr_entities:
        if meanings - (kz_entities | {'capital', 'city', 'country', 'past'}):
            return None
        if 'almaty' in meanings and 'astana' not in meanings:
            if 'past' in meanings:
                return answer('almaty_past', 'Была. Сейчас столица Астана')
            return answer('almaty_capital', 'Сейчас столица Астана' if negative else 'Раньше была. Сейчас Астана')
        return answer('kazakhstan_capital', 'Столица Казахстана Астана')
    if 'capital' in meanings and meanings & tr_entities and not meanings & kz_entities:
        if meanings - (tr_entities | {'capital', 'city', 'country'}):
            return None
        return answer('turkey_capital', 'Столица Турции Анкара')
    if 'baikal' in meanings and meanings <= {'baikal', 'sea', 'lake'}:
        return answer('baikal_lake', 'Это очень большое озеро')
    if 'antarctica' in meanings and meanings <= {'antarctica', 'north', 'south', 'hemisphere'}:
        return answer('antarctica_south', 'В Южном полушарии')
    if 'taiwan' in meanings:
        # The team chose this short game reply for the affirmative independence
        # question. Other Taiwan questions keep their own relation and polarity.
        if not negative and 'independent' in meanings and meanings <= {'taiwan', 'country', 'independent', 'island'}:
            return answer('taiwan_independent', 'Да')
        # 'Китай город Тайваня' has China as its subject, not Taiwan.
        if 'city' in meanings and 'china' in meanings and 'тайвань' not in words:
            return None
        if meanings <= {'taiwan', 'china', 'city', 'island'}:
            if 'city' in meanings:
                return answer('taiwan_island', 'Это остров, а не город')
            if 'island' in meanings:
                return answer('taiwan_island', 'Это остров')
        if meanings <= {'taiwan', 'china', 'country', 'independent', 'part', 'status', 'island'} and meanings & {'country', 'independent', 'part', 'status'}:
            return answer('taiwan_status', 'Тайвань управляет собой, а Китай считает его своей территорией')
    return None
