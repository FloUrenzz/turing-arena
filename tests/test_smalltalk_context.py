from copy import deepcopy
import unittest

from arena.smalltalk import conversational_reply, strip_question_preamble


def state_after(question, text, topic=None):
    return {'history': [{'question': question, 'text': text, 'topic': topic}], 'turn': 1}


def append(state, question, result):
    state['history'].append({'question': question, 'text': result['text'], 'topic': result['topic']})


class SmalltalkChecks(unittest.TestCase):
    def test_screenshot_chain_neutral_mood_and_activity_typos(self):
        greeting = conversational_reply('Салам как дела', {})
        self.assertEqual(greeting['text'], 'Салам, всё чётко, сам как?')
        state = state_after('Салам как дела', greeting['text'], greeting['topic'])
        mood = conversational_reply('да пойдёт', state)
        self.assertEqual(mood['text'], 'Понял. Чем занимаешься?')
        append(state, 'да пойдёт', mood)
        first = conversational_reply('че делашь', state)
        self.assertEqual(first['text'], 'Да ничё особенного. А ты?')
        append(state, 'че делашь', first)
        repeated = conversational_reply('че далешь', state)
        self.assertEqual(repeated['text'], 'Сейчас просто общаюсь с тобой')

    def test_short_mood_variants_require_relevant_context(self):
        mood = state_after('Салам', 'Салам, всё чётко, сам как?')
        for question in ('да пойдёт', 'да пойдет', 'ну пойдёт', 'вроде пойдет',
                         'терпимо', 'да более-менее', 'более менее', 'да нормас',
                         'да ниче', 'ничё', 'потихоньку', 'да потихоньку'):
            with self.subTest(question=question):
                self.assertIsNotNone(conversational_reply(question, mood))
        unrelated = state_after('Сколько 17 плюс 6?', '23')
        for question in ('пойдет', 'да пойдет', 'да нормас', 'ничё', 'потихоньку',
                         'да не пойдет', 'у друга пойдет', 'пойдет завтра дождь'):
            with self.subTest(question=question):
                self.assertIsNone(conversational_reply(question, unrelated))

    def test_activity_typos_are_bounded_to_complete_questions(self):
        for question in ('че делаешь', 'че делаеш', 'че делашь', 'че далешь',
                         'чо делаш', 'че делаешъ', 'а чё ты делаешь?', 'че щас делаеш'):
            with self.subTest(question=question):
                self.assertEqual(conversational_reply(question, {})['text'], 'Да ничё особенного. А ты?')
        for question in ('че делаешь завтра', 'че делашь завтра', 'ты не делаешь',
                         'че ты не делаешь', 'че друг делает', 'че делашь с проектом',
                         'че далешь, если будет дождь'):
            self.assertIsNone(conversational_reply(question, {}), question)

    def test_reordered_exam_report_keeps_result_and_speaker(self):
        self.assertEqual(conversational_reply('Экзамен сегодня я сдал', {})['text'], 'О, имба. Как прошло?')
        self.assertIn('Обидненько', conversational_reply('Экзамен сегодня не сдал', {})['text'])
        for question in ('Друг сегодня сдал экзамен', 'Сегодня я сдал экзамен?',
                         'Экзамен завтра сдам', 'Не экзамен сегодня сдал'):
            self.assertIsNone(conversational_reply(question, {}), question)

    def test_opening_without_punctuation(self):
        for text in ('привет как дела', 'салам как дела', 'ку как сам'):
            result = conversational_reply(text, {})
            self.assertIsNotNone(result)
            state = state_after(text, result['text'], result['topic'])
            answer = conversational_reply('да норм', state)
            self.assertEqual(answer['text'], 'О, хорошо. Чем занимаешься?')
            append(state, 'да норм', answer)
            self.assertEqual(conversational_reply('да тоже ничего особенного', state)['text'], 'Понял. Как день прошёл?')

    def test_plain_greeting_does_not_answer_an_unasked_question(self):
        for text, expected, next_question, next_expected in (
            ('привет!', 'Привет', 'привет как дела', 'Привет, норм, сам как?'),
            ('Салам', 'Салам', 'салам как дела', 'Салам, всё чётко, сам как?'),
            ('ку', 'Ку', 'ку как сам', 'Ку, норм, ты как?'),
        ):
            with self.subTest(text=text):
                result = conversational_reply(text, {})
                self.assertEqual(result, {'text': expected, 'topic': 'smalltalk:greeting'})
                state = state_after(text, result['text'], result['topic'])
                self.assertEqual(conversational_reply(next_question, state)['text'], next_expected)

    def test_question_preamble_waits_only_when_the_question_is_missing(self):
        for text in ('КРЧ у меня вопрос', 'Короче, у меня к тебе вопрос', 'Есть вопрос',
                     'У меня вопрос:', 'Можно вопрос?', 'Слушай, можно задать вопрос?'):
            with self.subTest(text=text):
                self.assertEqual(strip_question_preamble(text), text)
                self.assertEqual(conversational_reply(text, {})['text'], 'Давай, спрашивай')
        full_question = 'Крч, у меня вопрос: сколько будет 17 плюс 6?'
        self.assertEqual(strip_question_preamble(full_question), 'сколько будет 17 плюс 6?')
        self.assertIsNone(conversational_reply(full_question, {}))

    def test_nothing_then_day_then_normal_then_detail(self):
        state = state_after('Что делаешь?', 'Да ничё особенного. А ты?')
        result = conversational_reply('да тоже ничего особенного', state)
        self.assertEqual(result['text'], 'Понял. Как день прошёл?')
        append(state, 'да тоже ничего особенного', result)
        result = conversational_reply('норм', state)
        self.assertEqual(result['text'], 'О, хорошо. Что-нибудь интересное было?')
        append(state, 'норм', result)
        result = conversational_reply('нет', state)
        self.assertEqual(result['text'], 'Понял, обычный день')

    def test_casual_nothing_variants(self):
        state = state_after('Чё делаешь?', 'Да ничё особенного. А ты?')
        for text in ('да тоже ничего', 'я тоже ничё', 'ну тоже ничо особенного', 'ничего', 'ничего особенного'):
            with self.subTest(text=text):
                self.assertIsNotNone(conversational_reply(text, state))
        self.assertIsNone(conversational_reply('ничего', {}))

    def test_bad_mood_is_not_positive(self):
        state = state_after('Привет', 'Привет, как дела?')
        for text in ('не норм', 'не очень', 'так себе', 'плохо'):
            result = conversational_reply(text, state)
            self.assertIn('Что случилось?', result['text'])
            self.assertNotIn('хорошо', result['text'])

    def test_unknown_yes_and_other_speakers_not_consumed(self):
        for state in ({}, state_after('17 плюс 6', '23')):
            for text in ('да', 'нет', 'а ты?', 'норм'):
                self.assertIsNone(conversational_reply(text, state), text)
        state = state_after('Что делаешь?', 'Да ничё особенного. А ты?')
        for text in ('ничего не работает', 'ничего не знаю об интегралах', 'друг ничего не делает',
                     'не ничего особенного', 'ничего особенного, но почему радуга круглая?',
                     'я не слушаю музыку', 'сколько будет два плюс два', 'меня зовут Нуркен',
                     'Ты любишь чай?', 'флюмп квазибрум', '«норм»', 'нет, я не согласен с формулой'):
            self.assertIsNone(conversational_reply(text, state), text)

    def test_elliptical_context_does_not_use_old_turn(self):
        state = state_after('Как дела?', 'Норм, сам как?')
        state['history'].append({'question': '17 плюс 6', 'text': '23', 'topic': None})
        self.assertIsNone(conversational_reply('норм', state))
        self.assertIsNone(conversational_reply('а ты?', state))

    def test_no_repeat_question_from_recent_turns(self):
        state = state_after('Привет', 'Как день прошёл?')
        state['history'].append({'question': 'Что делаешь?', 'text': 'Да ничё особенного. А ты?'})
        result = conversational_reply('да тоже ничего', state)
        self.assertNotIn('Как день прошёл?', result['text'])
        self.assertEqual(result['text'], 'Оке. Что планируешь дальше?')

    def test_specific_followup_chains(self):
        examples = [
            ('готовлюсь к экзамену', 'По какому предмету экзамен?', 'по физике', 'А какая тема сложнее всего?'),
            ('делаю домашку', 'По какому предмету?', 'математика', 'А какая тема сложнее всего?'),
            ('слушаю музыку', 'А что за музыка?', 'рок', 'А есть любимый трек?'),
            ('жду друга', 'Давно ждёшь?', 'уже полчаса', 'Он написал, когда подойдёт?'),
            ('у меня выходной', 'О, каеф. Уже придумал, чем займёшься?', 'пока не знаю', 'Можно пока никуда не спешить'),
            ('Смотрю фильм', 'А что смотришь?', 'комедию', 'Как тебе пока?'),
            ('Слушаю музыку', 'А что за музыка?', 'разную', 'А что сейчас играет?'),
            ('Я сегодня сдал экзамен', 'О, имба. Как прошло?', 'вроде нормально', 'О, имба. Что за предметы были?'),
        ]
        for first, question, answer, expected in examples:
            with self.subTest(first=first):
                result = conversational_reply(first, {})
                self.assertEqual(result['text'], question)
                state = state_after(first, result['text'], result['topic'])
                self.assertEqual(conversational_reply(answer, state)['text'], expected)

    def test_yes_no_answers_to_known_questions(self):
        examples = [('Хочешь поболтать?', 'да', 'Давай. О чём хочешь поговорить?'),
                    ('Хочешь поболтать?', 'не хочу', 'Оке, как захочешь'),
                    ('А результаты уже вышли?', 'нет', 'Тогда пока рано себя накручивать'),
                    ('А результаты уже вышли?', 'да', 'И как в итоге?'),
                    ('А будильник ставил?', 'да', 'Не услышал его?'),
                    ('Сложные задания были?', 'да', 'Что было самым сложным?'),
                    ('Много ещё осталось?', 'нет', 'О, уже почти закончил'),
                    ('А есть любимый трек?', 'да', 'Как называется?')]
        for prompt, answer, expected in examples:
            self.assertEqual(conversational_reply(answer, state_after('', prompt))['text'], expected)

    def test_reciprocal_followups_and_prefixed_acknowledgments(self):
        examples = [
            ('норм', 'О, хорошо. Что-нибудь интересное было?', 'smalltalk:day_detail', 'а ты?',
             'Да ничего особенного, с тобой общаюсь'),
            ('комедию', 'Как тебе пока?', 'smalltalk:movie', 'а ты?', 'Я сейчас с тобой общаюсь'),
            ('рок', 'А есть любимый трек?', 'smalltalk:music', 'а у тебя?',
             'Сейчас ничего не слушаю, общаюсь с тобой'),
        ]
        for previous, bot, topic, question, expected in examples:
            with self.subTest(question=question, topic=topic):
                self.assertEqual(conversational_reply(question, state_after(previous, bot, topic))['text'], expected)
        for text in ('ну ладно', 'да ладно'):
            self.assertEqual(conversational_reply(text, {})['text'], 'Оке')

    def test_style_and_state_not_mutated(self):
        state = state_after('Привет', 'Как дела?')
        before = deepcopy(state)
        for text in ('норм', 'так себе', 'просто отдыхаю', 'смотрю фильм', 'скучно', 'спасибо', 'понятно'):
            result = conversational_reply(text, state)
            self.assertFalse(result['text'].endswith('.'))
            self.assertNotIn('—', result['text'])
            self.assertLess(len(result['text']), 150)
        self.assertEqual(before, state)


if __name__ == '__main__':
    unittest.main()
