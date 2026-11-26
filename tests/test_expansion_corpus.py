from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from arena.corpus import Corpus
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.expansion_corpus import BASE_NAME, EXPANSION_NAME, lookup_key, utterance_key
from arena.expansion_keywords import build_keyword_index
from arena.models import initial_state


class ExpansionCorpusChecks(unittest.TestCase):
    def test_expansion_is_a_fallback_for_the_bundled_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            base = data / BASE_NAME
            extra = data / EXPANSION_NAME
            question = 'Хочу сложить шарф и запасной фонарик в дорожную сумку'
            answer = 'Положи фонарик поближе, чтобы быстро достать'
            exam = 'Что взять на устную проверку?'
            exam_reply = 'Глянь требования, там обычно пишут, что нужно принести'
            with closing(sqlite3.connect(base)) as db:
                db.executescript('''
                    CREATE TABLE corpus_metadata(key TEXT, value TEXT);
                    INSERT INTO corpus_metadata VALUES ('schema_version', '1');
                    CREATE TABLE corpus_replies(source_id INTEGER, approved INTEGER);
                    CREATE TABLE corpus_sources(id INTEGER, filename TEXT);
                ''')
            with closing(sqlite3.connect(extra)) as db:
                db.executescript('''
                    CREATE TABLE scenarios(id INTEGER PRIMARY KEY, topic TEXT, answer TEXT);
                    CREATE TABLE utterances(lookup BLOB PRIMARY KEY, id INTEGER, scenario_id INTEGER);
                ''')
                db.execute('INSERT INTO scenarios VALUES (1, ?, ?)', ('Дорога', answer))
                db.executemany('INSERT INTO utterances VALUES (?, ?, 1)',
                               [(lookup_key(utterance_key(text)), number) for number, text in
                                enumerate((question, '37 умножить на 19'), 1)])
                db.execute('INSERT INTO scenarios VALUES (2, ?, ?)', ('Учёба', exam_reply))
                db.execute('INSERT INTO utterances VALUES (?, 3, 2)', (lookup_key(utterance_key(exam)),))
                db.commit()

            corpus = Corpus(base)
            knowledge = ensure_demo_database()
            state = initial_state()
            found = generate(question.upper() + '!', state, knowledge, corpus_snapshot=corpus)
            self.assertEqual(found['text'], answer)
            self.assertIn('method=expansion', found['trace'][0])
            self.assertIsNone(corpus.match_expansion('Не ' + question.lower()))
            self.assertEqual(generate('37 умножить на 19', state, knowledge, corpus_snapshot=corpus)['text'], '703')
            self.assertTrue(generate(question, state, knowledge)['fallback'])
            self.assertEqual(generate(exam, state, knowledge, corpus_snapshot=corpus)['text'], exam_reply)

    def test_keyword_lookup_handles_reordering_and_rejects_changed_meaning(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            extra = data / EXPANSION_NAME
            base = data / BASE_NAME
            answer = 'Помнишь, где была эта заставка?'
            prompt = 'Не могу вспомнить мелодию из заставки'
            with closing(sqlite3.connect(base)) as db:
                db.executescript('''
                    CREATE TABLE corpus_metadata(key TEXT, value TEXT);
                    INSERT INTO corpus_metadata VALUES ('schema_version', '1');
                    CREATE TABLE corpus_replies(source_id INTEGER, approved INTEGER);
                    CREATE TABLE corpus_sources(id INTEGER, filename TEXT);
                ''')
            with closing(sqlite3.connect(extra)) as db:
                db.executescript('''
                    CREATE TABLE scenarios(id INTEGER PRIMARY KEY, topic TEXT, prompt TEXT, answer TEXT);
                    CREATE TABLE utterances(lookup BLOB PRIMARY KEY, id INTEGER, scenario_id INTEGER);
                ''')
                db.executemany('INSERT INTO scenarios VALUES (?, ?, ?, ?)', [
                    (1, 'Музыка', prompt, answer),
                    (2, 'Фильмы', 'Остановился на середине серии', 'Что тебя отвлекло?'),
                    (3, 'Учёба', 'На середине серии остановился', 'Речь про серию упражнений?'),
                ])
                db.execute('INSERT INTO utterances VALUES (?, 1, 1)', (lookup_key(utterance_key(prompt)),))
                build_keyword_index(db)
                db.commit()

            corpus = Corpus(base)
            query = 'Слушай, мелодию из заставки я не могу вспомнить'
            knowledge = ensure_demo_database()
            found = generate(query, initial_state(), knowledge, corpus_snapshot=corpus)
            self.assertEqual(found['text'], answer)
            self.assertEqual(found['topic'], 'corpus:Музыка')
            self.assertIn('method=expansion-keywords', found['trace'][0])
            self.assertEqual(corpus.match_expansion(prompt, keywords=True)['method'], 'expansion')
            for ambiguous in ('Музыка', 'Мелодию из заставки я могу вспомнить',
                              'Мелодию из заставки друг не может вспомнить',
                              'На середине серии я остановился', query + '. Как встретиться?'):
                with self.subTest(prompt=ambiguous):
                    self.assertIsNone(corpus.match_expansion(ambiguous, keywords=True))
