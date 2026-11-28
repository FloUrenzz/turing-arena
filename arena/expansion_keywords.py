"""Keyword retrieval over the scenario prompts of the larger local corpus."""

from collections import Counter, defaultdict
import math
import re

from .retrieval import keyword_features, keyword_score, keyword_topic_terms


_OPENING = re.compile(r'^(?:слушай|кстати|смотри|короче|ну вот|в общем)[,:]?\s+', re.I)
_MAX_CANDIDATES = 80
_TOPIC_WORDS = {
    'Музыка': 'музыка музыку музыкой мелодия мелодии трек песня песни альбом плейлист',
    'Фильмы': 'фильм фильмы кино сериал сериалы мультсериал мультфильм',
    'Компьютер и файлы': 'компьютер ноутбук драйвер драйвера флешка файлы',
    'Программирование': 'программирование программист python javascript компилятор',
    'Дорога и транспорт': 'автобус метро маршрутка трамвай поезд такси',
    'Подготовка к проверкам': 'экзамен экзамены зачет контрольная',
    'Домашние задания': 'домашка домашнее задание',
    'Спорт': 'футбол баскетбол волейбол тренировка соревнования спорт',
    'Книги': 'книга книги книжка чтение',
    'Домашняя еда': 'рецепт выпечка готовка',
    'Игры': 'видеоигра видеоигры геймплей геймпад',
    'Погода и день': 'погода погоду прогноз снегопад ливень',
    'Подготовка к выступлению': 'выступление презентация репетиция доклад',
    'Одежда и вещи': 'одежда куртка кроссовки',
}
_TOPIC_ANCHORS = {term: topic for topic, words in _TOPIC_WORDS.items()
                  for term in keyword_topic_terms(words)}


def build_keyword_index(db):
    """Index scenario prompts, with all changes inside the caller's transaction."""
    documents = []
    frequencies = Counter()
    for identifier, prompt in db.execute('SELECT id, prompt FROM scenarios'):
        features = keyword_features(prompt)
        if features is not None:
            terms = features['terms']
            documents.append((identifier, terms))
            frequencies.update(terms)

    weights = {term: 1 + math.log((len(documents) + 1) / (count + 1))
               for term, count in frequencies.items()}
    db.execute('DROP TABLE IF EXISTS keyword_postings')
    db.execute('DROP TABLE IF EXISTS keyword_weights')
    db.execute('DROP TABLE IF EXISTS keyword_documents')
    db.execute('''CREATE TABLE keyword_postings (
        term TEXT, scenario_id INTEGER, PRIMARY KEY (term, scenario_id)
    ) WITHOUT ROWID''')
    db.execute('CREATE TABLE keyword_weights (term TEXT PRIMARY KEY, weight REAL) WITHOUT ROWID')
    db.execute('CREATE TABLE keyword_documents (scenario_id INTEGER PRIMARY KEY, weight REAL)')
    db.executemany('INSERT INTO keyword_weights VALUES (?, ?)', sorted(weights.items()))
    db.executemany('INSERT INTO keyword_documents VALUES (?, ?)',
                   ((identifier, sum(weights[term] for term in sorted(terms))) for identifier, terms in documents))
    db.executemany('INSERT INTO keyword_postings VALUES (?, ?)',
                   sorted((term, identifier) for identifier, terms in documents for term in terms))
    return len(documents), len(weights)


def find_keyword_reply(db, question):
    """Return the best guarded match, or ask the ordinary pipeline to continue."""
    core = _OPENING.sub('', question.strip(), count=1)
    if re.search(r'[.!?;]\s+\w', core):
        return None
    query = keyword_features(core)
    if query is None:
        return None
    terms = sorted(query['terms'])
    placeholders = ','.join('?' for _ in terms)
    weights = dict(db.execute(f'SELECT term, weight FROM keyword_weights WHERE term IN ({placeholders})', terms))
    if len(weights) != len(terms):
        return None

    query_weight = sum(weights[term] for term in terms)
    candidates = db.execute(f'''
        SELECT s.id, s.topic, s.prompt, s.answer, d.weight, hits.overlap
        FROM (
            SELECT p.scenario_id, SUM(w.weight) AS overlap
            FROM keyword_postings p JOIN keyword_weights w ON w.term = p.term
            WHERE p.term IN ({placeholders})
            GROUP BY p.scenario_id
            HAVING COUNT(*) >= 2 AND SUM(w.weight) >= ?
            ORDER BY overlap DESC, p.scenario_id
            LIMIT ?
        ) AS hits
        JOIN scenarios s ON s.id = hits.scenario_id
        JOIN keyword_documents d ON d.scenario_id = hits.scenario_id
    ''', (*terms, .90 * query_weight - 1e-9, _MAX_CANDIDATES + 1)).fetchall()
    if len(candidates) > _MAX_CANDIDATES:
        # The query is too broad to check every potentially competing answer.
        return None
    matches = []
    for identifier, topic, prompt, answer, weight, overlap in candidates:
        document = keyword_features(prompt)
        if document is None:
            continue
        score = keyword_score(query, document, query_weight, weight, overlap)
        if score is not None:
            matches.append((score, identifier, topic, answer))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1]))
    score, identifier, topic, answer = matches[0]
    if any(score - other_score < .07 and (topic != other_topic or answer != other_answer)
           for other_score, _, other_topic, other_answer in matches[1:]):
        return None
    return identifier, topic, answer, round(score, 4)


def find_keyword_topic(db, question):
    """Vote for topics using words concentrated in those topics across scenarios."""
    terms = sorted(keyword_topic_terms(_OPENING.sub('', question.strip(), count=1)))
    if not terms:
        return None
    anchors = {_TOPIC_ANCHORS[term] for term in terms if term in _TOPIC_ANCHORS}
    if anchors:
        return next(iter(anchors)) if len(anchors) == 1 else None

    placeholders = ','.join('?' for _ in terms)
    counts = defaultdict(list)
    for term, topic, count, weight in db.execute(f'''
        SELECT p.term, s.topic, COUNT(*), w.weight
        FROM keyword_postings p
        JOIN scenarios s ON s.id = p.scenario_id
        JOIN keyword_weights w ON w.term = p.term
        WHERE p.term IN ({placeholders})
        GROUP BY p.term, s.topic
    ''', terms):
        counts[term].append((topic, count, weight))

    scores = defaultdict(float)
    support = Counter()
    strong = set()
    for hits in counts.values():
        total = sum(count for _, count, _ in hits)
        for topic, count, weight in hits:
            share = count / total
            if count >= 2 and share >= .6:
                scores[topic] += weight * share
                support[topic] += 1
                if count >= 6 and share >= .8:
                    strong.add(topic)
    ranked = sorted(scores, key=lambda topic: (-scores[topic], topic))
    if not ranked:
        return None
    best = ranked[0]
    if support[best] < 2 and best not in strong:
        return None
    if len(ranked) > 1 and scores[best] < 1.5 * scores[ranked[1]]:
        return None
    return best
