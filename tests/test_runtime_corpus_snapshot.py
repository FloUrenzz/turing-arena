from pathlib import Path
from contextlib import closing
import pickle
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from arena.corpus import Corpus
from arena.corpus_import import build_corpus
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import initial_state
from arena.runtime import Runtime


ROOT = Path(__file__).resolve().parents[1]


def custom_worker(question, state, db_path, seed):
    return {'text': 'Оке', 'intent': 'conversation', 'topic': None,
            'fallback': False, 'updates': {}, 'facts': [], 'concepts': [], 'trace': []}


class RuntimeCorpusSnapshotChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = Path(cls.folder.name) / 'corpus.sqlite3'
        build_corpus((ROOT / 'datasets').glob('*.xlsx'), cls.path,
                     review_path=ROOT / 'data/corpus_review.json')
        cls.lexicon = ensure_demo_database()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_snapshot_built_once_and_used_after_source_disappears(self):
        local_path = Path(self.folder.name) / 'temporary-copy.sqlite3'
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(local_path)) as target:
            source.backup(target)
        original_init = Corpus.__init__
        with patch.object(Corpus, '__init__', autospec=True, side_effect=original_init) as loader:
            runtime = Runtime(self.lexicon, corpus_path=local_path)
            self.assertEqual(loader.call_count, 1)
            self.assertIsNotNone(runtime._corpus_snapshot._approximate_index)
            local_path.unlink()
            first = runtime.respond('Привет, как дела?', request_id='one')
            second = runtime.respond('Не могу найти ключии, хотя точно принёс их домой')
            self.assertEqual(loader.call_count, 1)
        self.assertEqual(first['status'], 'ok')
        self.assertEqual(first['text'], 'Привет, норм, сам как?')
        self.assertEqual(second['status'], 'ok')
        self.assertEqual(second['text'], 'В карманах и сумке смотрел?')
        self.assertIn('method=approximate', second['trace'][0])
        self.assertTrue(runtime.respond('Привет, как дела?', request_id='one')['duplicate'])
        self.assertEqual(runtime.state['turn'], 2)

    def test_trusted_memory_roundtrip_preserves_index_and_corrections(self):
        snapshot = Corpus(self.path)
        snapshot.prepare_approximate()
        serialized = pickle.dumps(snapshot, protocol=pickle.HIGHEST_PROTOCOL)
        restored = pickle.loads(serialized)
        self.assertEqual(len(restored.rows), len(snapshot.rows))
        self.assertEqual(restored._approximate_index.token_matcher.vocabulary,
                         snapshot._approximate_index.token_matcher.vocabulary)
        self.assertEqual(restored._approximate_index.token_matcher.correct(['привте']),
                         (['привет'], [('привте', 'привет')]))
        with patch('arena.corpus.Corpus', side_effect=AssertionError('unexpected reload')):
            reply = generate('Привет, как дела?', initial_state(), self.lexicon,
                             corpus_path=self.path, corpus_snapshot=restored)
        self.assertEqual(reply['text'], 'Привет, норм, сам как?')

    def test_no_corpus_custom_worker_and_invalid_path_keep_previous_behavior(self):
        with patch('arena.corpus.Corpus', side_effect=AssertionError('must not load')):
            plain = Runtime(self.lexicon)
            custom = Runtime('unused', worker=custom_worker, corpus_path='missing.sqlite3')
        self.assertIsNone(plain._corpus_snapshot)
        self.assertIsNone(custom._corpus_snapshot)
        self.assertEqual(custom.respond('привет')['text'], 'Оке')
        invalid = Runtime(self.lexicon, corpus_path=Path(self.folder.name) / 'missing.sqlite3')
        self.assertIsNone(invalid._corpus_snapshot)
        self.assertEqual(invalid.respond('17 + 6')['text'], '23')
        self.assertEqual(invalid.respond('Привет')['status'], 'error')


if __name__ == '__main__':
    unittest.main()
