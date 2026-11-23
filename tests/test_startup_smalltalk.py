from copy import deepcopy
from pathlib import Path
import unittest

from arena.corpus import Corpus
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import initial_state, apply_reply
from arena.smalltalk import conversational_reply


ROOT = Path(__file__).resolve().parents[1]


class StartupSmalltalkChecks(unittest.TestCase):
    def test_first_person_startup_activity_variants(self):
        for question in (
            'Как и ты новые стартапы придумываю',
            'Я, как и ты, придумываю новые стартапы',
            'Так же как ты, новый стартап обдумываю',
            'Я тоже придумываю стартап',
            'Ну я сейчас свой стартап продумываю',
            'Думаю над новым стартапом',
            'Ищу идеи для стартапа',
            'Новые идеи для стартапов придумываю',
        ):
            with self.subTest(question=question):
                result = conversational_reply(question, {})
                self.assertIsNotNone(result)
                self.assertEqual(result['text'], 'Есть уже какая-нибудь идея?')
                self.assertEqual(result['topic'], 'smalltalk:startup')

    def test_negation_questions_and_other_actors_are_not_discarded(self):
        for question in (
            'Как и ты не придумываю новые стартапы',
            'Я не обдумываю стартап',
            'Мой друг придумывает новые стартапы',
            'Почему ты придумываешь новые стартапы?',
            'Придумай новые стартапы',
            'Я придумываю стартапы?',
            'Как и ты, новые стартапы придумываю, но мне это надоело',
            '«Как и ты новые стартапы придумываю»',
            'Я придумываю стартапы\nа друг решает задачу',
        ):
            with self.subTest(question=question):
                self.assertIsNone(conversational_reply(question, {}))

    def test_contextual_yes_no_and_no_mutation(self):
        state = initial_state()
        question = 'Придумываю новый стартап'
        first = conversational_reply(question, state)
        state['history'] = [{'question': question, **first}]
        before = deepcopy(state)
        self.assertEqual(conversational_reply('пока нет', state)['text'], 'Оке, можно пока просто подумать')
        self.assertEqual(conversational_reply('ага', state)['text'], 'О, а что за идея?')
        self.assertEqual(state, before)
        self.assertIsNone(conversational_reply('пока нет', {}))

    def test_startup_answer_plus_reciprocal_question(self):
        self.assertEqual(conversational_reply('новые стартапы придумываю, а ты?', {})['text'],
                         'Сейчас просто общаюсь с тобой')

    def test_real_engine_screenshot_chain_with_full_corpus(self):
        corpus_path = ROOT / 'data/dialogue-combined-5350-v2.sqlite3'
        if not corpus_path.exists():
            self.skipTest('Full combined corpus is not present')
        corpus = Corpus(corpus_path)
        state = initial_state()
        for question, expected in (
            ('Салам как дела', 'Салам, всё чётко, сам как?'),
            ('Да пойдет', 'Понял. Чем занимаешься?'),
            ('Как и ты новые стартапы придумываю', 'Есть уже какая-нибудь идея?'),
            ('Пока нет', 'Оке, можно пока просто подумать'),
        ):
            reply = generate(question, state, ensure_demo_database(), corpus_snapshot=corpus)
            self.assertEqual(reply['text'], expected)
            self.assertFalse(reply['fallback'])
            state = apply_reply(state, question, reply)


if __name__ == '__main__':
    unittest.main()
