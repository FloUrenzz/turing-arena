import unittest

from arena.retrieval import ApproximateIndex


def row(prompt, answer='Ответ из базы', **extra):
    return {'id': prompt, 'prompt': prompt, 'answer': answer, 'context': '', **extra}


class ApproximateRetrievalChecks(unittest.TestCase):
    def test_returns_original_approved_row_for_reordered_informal_text(self):
        source = row('Закончил домашнее задание')
        result = ApproximateIndex([source]).match('Домашку я уже завершил')
        self.assertIs(result['row'], source)
        self.assertGreater(result['score'], .84)

    def test_capitalized_typo_is_corrected_without_rewriting_answer(self):
        source = row('Интернет пропал только на ноутбуке', 'А что пишет ноутбук?')
        result = ApproximateIndex([source]).match('Интерент пропал только на ноутбуке')
        self.assertIs(result['row'], source)
        self.assertIn(('интерент', 'интернет'), result['corrections'])

    def test_informal_synonyms_and_relative_clause(self):
        cases = [
            ('На товаре коробка вся мятая', 'У товара вся упаковка помята'),
            ('Наша компания никак не согласует время встречи',
             'Компания никак не может договориться о времени встречи'),
            ('Сегодня всё раздражает по мелочам', 'Сегодня даже мелочи раздражают'),
            ('Только сейчас вспомнил про вчерашний день рождения друга',
             'Только сейчас вспомнил, что вчера у друга был день рождения'),
            ('Впервые сходил на тренировку', 'На первую тренировку сходил'),
        ]
        for prompt, question in cases:
            with self.subTest(question=question):
                self.assertIsNotNone(ApproximateIndex([row(prompt)]).match(question))

    def test_protected_meaning_cannot_be_traded_for_overlap(self):
        cases = [
            ('Не понял условие домашки', 'Условие домашки понял'),
            ('Не хочу смотреть фильм, хочу читать книгу',
             'Хочу смотреть фильм, не хочу читать книгу'),
            ('Я написал другу длинное сообщение', 'Друг написал мне длинное сообщение'),
            ('Друг сказал, что я опоздал на встречу', 'Я сказал, что друг опоздал на встречу'),
            ('Решил 2 задачи и 3 примера', 'Решил 3 задачи и 2 примера'),
            ('Запомнил число -17', 'Запомнил число 17'),
            ('Сегодня нашел книгу', 'Вчера нашел книгу'),
            ('Летом ходил в школу', 'Зимой ходил в школу'),
            ('Нужен широкий стол и узкий шкаф', 'Нужен узкий стол и широкий шкаф'),
            ('Интернет пропал только на ноутбуке', 'Интернет пропал на ноутбуке'),
            ('Сначала поел потом уснул', 'Сначала уснул потом поел'),
            ('Нажал кнопку и программа сломалась', 'Программа сломалась и нажал кнопку'),
            ('До экзамена потерял ключи', 'После экзамена потерял ключи'),
            ('Почему пропал интернет?', 'Когда пропал интернет?'),
            ('Нашел первый вопрос в учебнике', 'Нашел последний вопрос в учебнике'),
            ('Ключи лежат в кармане', 'Ключи лежат в Армане'),
        ]
        for prompt, question in cases:
            with self.subTest(question=question):
                self.assertIsNone(ApproximateIndex([row(prompt)]).match(question))

    def test_unknown_content_and_quoted_literals_are_not_ignored(self):
        index = ApproximateIndex([row('Сегодня потерял ключи от квартиры')])
        for question in ('Сегодня потерял ключи от реактора',
                         'Сегодня потерял ключи от квартиры гиперпространства',
                         'Сегодня потерял «ключи от квартиры»',
                         'Сегодня потерял "ключи от квартиры'):
            with self.subTest(question=question):
                self.assertIsNone(index.match(question))

    def test_different_answers_with_equal_evidence_are_ambiguous(self):
        index = ApproximateIndex([
            row('Закончил домашнее задание', 'Первый ответ'),
            row('Домашку завершил', 'Второй ответ'),
        ])
        self.assertIsNone(index.match('Уже завершил домашку'))

    def test_duplicate_rows_with_same_answer_are_allowed(self):
        index = ApproximateIndex([row('Закончил домашнее задание'), row('Домашку завершил')])
        self.assertIsNotNone(index.match('Уже завершил домашку'))

    def test_context_is_checked_after_candidate_retrieval(self):
        source = row('Снова потерял ключи', context='expected dialogue')
        index = ApproximateIndex([source])
        history = [{'question': 'Ищу ключи', 'text': 'Уже нашел?'}]
        seen = []

        def check(candidate, candidate_history):
            seen.append((candidate, candidate_history))
            return candidate_history == history

        self.assertIsNone(index.match('Опять ключи потерял'))
        self.assertIsNone(index.match('Опять ключи потерял', (), check))
        result = index.match('Опять ключи потерял', history, check)
        self.assertIs(result['row'], source)
        self.assertIs(seen[-1][1], history)

    def test_empty_and_oversized_inputs_do_not_trigger_an_answer(self):
        index = ApproximateIndex([row('Потерял ключи от квартиры')])
        for question in ('', 'ключи', 'ключи ' * 200, None):
            with self.subTest(question=question):
                self.assertIsNone(index.match(question))


if __name__ == '__main__':
    unittest.main()
