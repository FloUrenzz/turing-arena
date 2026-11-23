import unittest

from arena.topic_fallbacks import topic_fallback


class TopicFallbackChecks(unittest.TestCase):
    def test_explicit_product_composition_queries(self):
        for text in (
            'состав шампуня', 'Какой состав у шампуня?',
            'Из чего состоит средство для мытья посуды?',
            'Расскажи, какие ингредиенты входят в этот крем',
            'Что входит в состав мыла', 'Пожалуйста, разбери состав зубной пасты',
            'назови компоненты геля для душа', 'Из чего сделан дезодорант?',
            'ingredients of shampoo', 'What is this soap made of?',
        ):
            with self.subTest(text=text):
                answer = topic_fallback(text)
                self.assertIsNotNone(answer)
                self.assertEqual(answer['topic'], 'composition')
                self.assertEqual(answer['text'], 'я не изучаю составы, тут не подскажу')

    def test_academic_requests_require_a_topic_and_request(self):
        for text in (
            'Объясни квантовую физику простыми словами',
            'Что такое фотосинтез?', 'Как устроен атом?',
            'Почему электроны не падают на ядро?',
            'Объясни термодинамику', 'Расскажи о химии',
            'Что изучает геология?', 'Реши интеграл от x',
            'Можешь объяснить квантовую физику?', 'Что такое энтропия?',
            'Could you explain quantum physics?', 'what is photosynthesis',
        ):
            with self.subTest(text=text):
                answer = topic_fallback(text)
                self.assertIsNotNone(answer)
                self.assertEqual(answer['topic'], 'academic')
                self.assertEqual(answer['text'], 'я в этом предмете не особо разбираюсь')

    def test_explicit_philosophical_requests(self):
        for text in (
            'В чём смысл жизни?', 'Зачем мы живем?',
            'Существует ли свобода воли?', 'Что есть истина?',
            'Объясни, что такое объективная истина',
            'Расскажи о философии', 'What is the meaning of life?',
            'Do we have free will?',
        ):
            with self.subTest(text=text):
                answer = topic_fallback(text)
                self.assertIsNotNone(answer)
                self.assertEqual(answer['topic'], 'philosophy')
                self.assertEqual(answer['text'], 'я над таким особо не задумывался')

    def test_mentions_school_social_and_unrelated_composition_do_not_trigger(self):
        for text in (
            'состав команды', 'Составь план', 'Как составить команду?',
            'Какой состав у команды по физике?', 'Я сегодня сдал экзамен по физике',
            'Какие дела у учителя физики?', 'Как дела у преподавателя химии?',
            'Я учусь на биолога', 'У меня завтра контрольная по математике',
            'Какую оценку мне поставит учитель физики?',
            'На шампуне написан состав', 'Мне нравится состав этого крема',
            'Я читал о квантовой физике', 'физика', 'философия',
            'Я над смыслом жизни размышлял', 'What did the physics teacher say?',
            'I passed my chemistry exam', 'My teacher mentioned quantum physics',
            'Какой состав у средства общения?',
            'Как называется фильм про квантовую физику?',
        ):
            with self.subTest(text=text):
                self.assertIsNone(topic_fallback(text))

    def test_personal_distress_is_not_casually_classified_as_philosophy(self):
        for text in (
            'Не вижу смысла в жизни', 'Зачем мне жить?',
            'В чем смысл моей жизни?', 'Что делать, если не вижу смысла жизни?',
            'Что делать, я не хочу жить', 'What is the meaning of my life?',
            'I want to die',
        ):
            with self.subTest(text=text):
                self.assertIsNone(topic_fallback(text))

    def test_foreign_input_still_gets_russian_response_with_text_limits(self):
        cases = (
            ('ingredients of shampoo', 'я не изучаю составы, тут не подскажу'),
            ('explain quantum physics', 'я в этом предмете не особо разбираюсь'),
            ('what is the meaning of life?', 'я над таким особо не задумывался'),
        )
        for question, expected in cases:
            answer = topic_fallback(question)
            self.assertEqual(answer['text'], expected)
            self.assertLessEqual(len(answer['text']), 300)
            self.assertFalse(answer['text'].endswith('.'))

    def test_other_questions_and_invalid_inputs_stay_with_main_pipeline(self):
        for text in (None, 3, '', ' ', '???', '17 + 6', 'умножь 37 на 19',
                     'Почему после дождя появляется радуга?',
                     'Что взять в Астану зимой?', 'Как дела?', 'x' * 2001):
            with self.subTest(text=text):
                self.assertIsNone(topic_fallback(text))


if __name__ == '__main__':
    unittest.main()
