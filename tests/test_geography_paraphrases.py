import unittest

from arena.geography import geography_reply


class GeographyParaphraseChecks(unittest.TestCase):
    def test_almaty_word_orders_and_ungrammatical_adjective(self):
        for question in ('Столица Казахстана Алматы?', 'А Алматы столица Казахстана',
                         'Алматы столица', 'казахстанский столица это Алматы же',
                         'Алма-Ата же столица Казахстана, да?', 'Слушай, Алматы является столицей Казахстана?',
                         'Столицей Казахстана считается Алматы?', 'Алматы столица РК что ли'):
            with self.subTest(question=question):
                self.assertEqual(geography_reply(question)['text'], 'Раньше была. Сейчас Астана')

    def test_negative_and_historical_claims_are_distinct(self):
        self.assertEqual(geography_reply('Алматы не столица Казахстана')['text'], 'Сейчас столица Астана')
        self.assertEqual(geography_reply('Алматы раньше была столицей?')['text'], 'Была. Сейчас столица Астана')
        self.assertIn('Астана', geography_reply('Астана не столица Казахстана?')['text'])

    def test_other_relations_generalize_without_wrong_fact(self):
        cases = {'Стамбул это турецкая столица': 'Столица Турции Анкара',
                 'Море это Байкал или озеро?': 'Это очень большое озеро',
                 'На севере Антарктида?': 'В Южном полушарии',
                 'Антарктида находится на севере': 'В Южном полушарии',
                 'Тайвань является самостоятельным государством': 'Да',
                 'Тайвань независимая страна': 'Да',
                 'Независимым государством является Тайвань?': 'Да',
                 'Китайским городом является Тайвань?': 'Это остров, а не город'}
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(geography_reply(question)['text'], expected)

    def test_requested_short_reply_does_not_affirm_other_relations(self):
        for question in ('Тайвань независимая страна?', 'Независимая страна это Тайвань?',
                         'А Тайвань независимое государство', 'Тайвань отдельная страна?'):
            self.assertEqual(geography_reply(question)['text'], 'Да')
        for question in ('Тайвань не независимая страна?', 'Тайвань город Китая?',
                         'Тайвань часть Китая?', 'Какой статус у Тайваня?'):
            self.assertNotEqual(geography_reply(question)['text'], 'Да')

    def test_unrelated_relations_and_multiple_questions_are_not_swallowed(self):
        for question in ('Алматы столица моды?', 'Почему Алматы перестала быть столицей?',
                         'Алматы столица Казахстана в 1990 году?', 'В Алматы вкусная еда?',
                         'Алматы столица? И какая завтра погода?', 'Мой друг говорит «Алматы столица»',
                         'Тайвань независимая страна и столица Китая Пекин?', 'Тайвань город и какой там климат?',
                         'Байкал самое глубокое море?', 'Антарктида в Северном полушарии зимой?',
                         'Китай это город Тайваня'):
            with self.subTest(question=question):
                self.assertIsNone(geography_reply(question))


if __name__ == '__main__':
    unittest.main()
