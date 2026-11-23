from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from arena.corpus import Corpus, context_fits
from arena.corpus_import import build_corpus


ROOT = Path(__file__).resolve().parents[1]


class ParaphraseRetrievalChecks(unittest.TestCase):
    def test_reordered_question_preserves_negation_actor_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'corpus.sqlite3'
            build_corpus((ROOT / 'datasets').glob('*.xlsx'), path,
                         review_path=ROOT / 'data/corpus_review.json')
            with closing(sqlite3.connect(path)) as db:
                ids = [row[0] for row in db.execute('SELECT id FROM corpus_replies WHERE approved=1 LIMIT 2')]
                db.execute('UPDATE corpus_replies SET approved=0')
                for identifier in ids:
                    db.execute("UPDATE corpus_replies SET approved=1,prompt='Я закончил презентацию',answer='О, хорошо',context='' WHERE id=?", (identifier,))
                    db.execute("UPDATE corpus_reviews SET context_turns_json='null' WHERE reply_id=?", (identifier,))
                db.commit()
                corpus = Corpus(path)
                self.assertEqual(corpus.match('Презентацию закончил')['text'], 'О, хорошо')
                self.assertEqual(corpus.match('Слушай, презентацию я завершил')['text'], 'О, хорошо')
                for question in ('Презентацию не закончил', 'Друг закончил презентацию',
                                 'Завтра закончу презентацию', 'Презентацию закончил?'):
                    self.assertIsNone(corpus.match(question), question)
                db.execute("UPDATE corpus_replies SET answer='Другой ответ' WHERE id=?", (ids[1],))
                db.commit()
            self.assertIsNone(Corpus(path).match('Презентацию закончил'))

    def test_paraphrased_context_requires_same_speaker_fact_and_recent_turn(self):
        turns = [{'role': 'user', 'text': 'Я закончил презентацию'},
                 {'role': 'bot', 'text': 'О, хорошо'}]
        history = [{'question': 'Презентацию закончил', 'text': 'О, хорошо'}]
        self.assertTrue(context_fits('', history, turns))
        for changed in (
            [{'question': 'Презентацию закончил?', 'text': 'О, хорошо'}],
            [{'question': 'Презентацию не закончил', 'text': 'О, хорошо'}],
            [{'question': 'О, хорошо', 'text': 'Презентацию закончил'}],
            history + [{'question': 'Как погода?', 'text': 'Не смотрел'}],
        ):
            self.assertFalse(context_fits('', changed, turns))


if __name__ == '__main__':
    unittest.main()
