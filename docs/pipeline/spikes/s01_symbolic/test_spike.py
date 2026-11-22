import unittest
from engine import Bot, calculate
from seed import seed
import tempfile
from pathlib import Path


class SpikeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bot = Bot(seed(Path(self.tmp.name) / 'demo.db'))

    def tearDown(self):
        self.bot.db.close()
        self.tmp.cleanup()

    def test_consistency_and_reason(self):
        self.assertIn('likes_tea', self.bot.answer('Тебе нравится чай?')['facts'])
        result = self.bot.answer('Почему ты не любишь чай?')
        self.assertIn('Вообще-то я люблю чай', result['text'])
        self.assertIn('likes_tea', result['facts'])
        self.assertIn('likes_tea', self.bot.answer('А почему?')['facts'])

    def test_unknown_not_chosen(self):
        self.assertTrue(self.bot.answer('Что выберешь: чай или пиццу?')['fallback'])

    def test_safe_calculator(self):
        self.assertEqual(calculate('17+26*2'), 69)
        for value in ('__import__("os")', '2**999', 'True+1', '1/0'):
            with self.assertRaises((ValueError, ZeroDivisionError)):
                calculate(value)

    def test_subject_not_invented(self):
        self.assertTrue(self.bot.answer('Я люблю кофе?')['fallback'])

    def test_user_identity(self):
        self.bot.answer('Меня зовут Оля')
        self.assertIn('Оля', self.bot.answer('Как меня зовут?')['text'])

    def test_pending_not_remembered(self):
        result = self.bot.prepare('Любишь музыку?')
        self.assertEqual(len(self.bot.history), 0)
        self.bot.commit('Любишь музыку?', result)
        self.assertEqual(len(self.bot.history), 1)

    def test_word_operation(self):
        self.assertEqual(self.bot.answer('Сколько букв в слове «привет»?')['text'], '6.')

    def test_group_and_clause(self):
        self.assertIn('likes_tea', self.bot.answer('Какой напиток ты предпочитаешь?')['facts'])
        self.assertIn('likes_music', self.bot.answer('Я люблю кофе, а ты любишь музыку?')['facts'])
        self.assertIn('likes_programming', self.bot.answer('Что ты любишь делать?')['facts'])

    def test_user_preferences_atomic(self):
        pending = self.bot.prepare('Я люблю музыку')
        self.assertEqual(self.bot.user_likes, {})
        self.bot.commit('Я люблю музыку',pending)
        self.assertIn('музыку',self.bot.answer('Что я люблю?')['text'])
        pending = self.bot.prepare('Меня зовут Дина')
        self.assertIsNone(self.bot.user_name)
        self.bot.commit('Меня зовут Дина',pending)
        self.assertEqual(self.bot.user_name,'Дина')

    def test_parentheses_and_alternatives(self):
        self.assertEqual(self.bot.answer('Сколько будет (2 + 3) * 4?')['text'],'20.')
        self.assertTrue(self.bot.answer('Чай или кофе или абракадабра?')['fallback'])

    def test_database_identity(self):
        self.bot.db.execute("UPDATE facts SET object='Дина' WHERE predicate='name'")
        self.bot.db.execute("UPDATE facts SET object='художник' WHERE predicate='role'")
        self.assertEqual(self.bot.answer('Как тебя зовут?')['text'],'Дина.')
        self.assertEqual(self.bot.answer('Кто ты?')['text'],'Я художник.')

    def test_first_question_survives_bound(self):
        self.bot.answer('Привет')
        for _ in range(40):
            self.bot.answer('Ты любишь чай?')
        self.assertEqual(len(self.bot.history),30)
        self.assertIn('Привет',self.bot.answer('Какой был первый вопрос?')['text'])


if __name__ == '__main__':
    unittest.main()
