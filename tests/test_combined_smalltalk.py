from copy import deepcopy
import unittest

from arena.smalltalk import conversational_reply


def after(question, text, topic):
    return {'history': [{'question': question, 'text': text, 'topic': topic}], 'turn': 1}


class CombinedSmalltalkChecks(unittest.TestCase):
    def setUp(self):
        self.activity = after('Да пойдет', 'Понял. Чем занимаешься?', 'smalltalk:activity')
        self.mood = after('Салам', 'Салам, всё чётко, сам как?', 'smalltalk:mood')

    def assert_reciprocal_answer(self, question, state, topic=None):
        result = conversational_reply(question, state)
        self.assertIsNotNone(result, question)
        self.assertTrue(result['text'].strip(), question)
        self.assertNotIn('а ты?', result['text'].casefold(), question)
        self.assertFalse(result['text'].endswith('.'), question)
        self.assertLessEqual(len(result['text']), 300, question)
        if topic:
            self.assertEqual(result['topic'], 'smalltalk:' + topic, question)
        return result

    def test_exact_screenshot_answer_and_question_in_one_message(self):
        result = self.assert_reciprocal_answer('да ничем сам чем занимаешься', self.activity, 'activity')
        self.assertEqual(result['text'], 'Да тоже ничего особенного, с тобой общаюсь')

    def test_activity_reply_composes_with_reciprocal_question(self):
        for question in ('ничем, а ты?', 'да ничем, сам чем занимаешься?',
                         'ничего. А ты?', 'да тоже ничего особенного а ты?',
                         'смотрю фильм, а ты что делаешь?', 'сижу дома, а ты чем занят?'):
            with self.subTest(question=question):
                self.assert_reciprocal_answer(question, self.activity, 'activity')

    def test_mood_reply_composes_with_explicit_mood_question(self):
        for question in ('нормально, сам как?', 'да пойдет, а ты как?',
                         'у меня всё нормально, а у тебя как дела?'):
            with self.subTest(question=question):
                self.assert_reciprocal_answer(question, self.mood, 'mood')

    def test_explicit_activity_question_does_not_require_history(self):
        for question in ('сам чем занимаешься', 'а ты чем занят?', 'а сам что делаешь?'):
            with self.subTest(question=question):
                result = conversational_reply(question, {})
                self.assertIsNotNone(result, question)
                self.assertEqual(result['topic'], 'smalltalk:activity')

    def test_explicit_question_controls_topic_when_answer_changes_subject(self):
        self.assert_reciprocal_answer('нормально, а ты чем занимаешься?', self.mood, 'activity')
        self.assert_reciprocal_answer('да ничем, а ты как?', self.activity, 'mood')

    def test_bare_nothing_uses_only_recent_activity_context(self):
        for question in ('ничем', 'да ничем', 'ну ничем'):
            with self.subTest(question=question):
                self.assertIsNotNone(conversational_reply(question, self.activity))
                self.assertIsNone(conversational_reply(question, {}))
                stale = deepcopy(self.activity)
                stale['history'].append({'question': '17 плюс 6', 'text': '23', 'topic': None})
                self.assertIsNone(conversational_reply(question, stale))

    def test_compound_parser_preserves_unrelated_qualifiers_and_roles(self):
        for question in ('друг ничем не занят, а ты?', 'да ничем сам чем не занимаешься',
                         'да ничем, сам чем занимаешься завтра', 'ничего не работает а ты?',
                         'ничего не знаю о физике, а ты?', 'смотрю фильм, а ты что делаешь с проектом?',
                         '«да ничем сам чем занимаешься»', '"ничем, а ты?"',
                         'да ничем\nсам чем занимаешься', 'не ничего, а ты?',
                         'да ничем, сам чем занимаешься и сколько будет 2 плюс 2?'):
            with self.subTest(question=question):
                self.assertIsNone(conversational_reply(question, self.activity), question)

    def test_composed_reply_does_not_mutate_state(self):
        before = deepcopy(self.activity)
        self.assert_reciprocal_answer('да ничем сам чем занимаешься', self.activity)
        self.assertEqual(self.activity, before)


if __name__ == '__main__':
    unittest.main()
