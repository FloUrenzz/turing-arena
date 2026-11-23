import unittest

from arena.gibberish import classify_gibberish


class GibberishChecks(unittest.TestCase):
    def test_user_example_and_clear_keyboard_noise(self):
        cases = {
            'впжтьеузшприекщгиек9хгщитеу0хщитк9хещрит9зек': 'cyrillic',
            'asdkjfh89': 'latin',
            'asdfghjkl': 'latin',
            'qwertyuiop': 'latin',
            'lkjhgfdsa': 'latin',
            'йцукенгшщ': 'cyrillic',
            'фывапролдж': 'cyrillic',
            'sdkjfhgklzmxv': 'latin',
            'жфпцтшщклврдг': 'cyrillic',
        }
        for value, script in cases.items():
            with self.subTest(value=value):
                result = classify_gibberish(value)
                self.assertIsNotNone(result)
                self.assertEqual(result.script, script)
                self.assertEqual(result.has_digits, any(char.isdigit() for char in value))

    def test_repeated_letters_are_a_separate_kind(self):
        for value in ('аааааа', 'aaaaaaaa', 'хахахахаха', 'лалалалалала'):
            with self.subTest(value=value):
                self.assertEqual(classify_gibberish(value).kind, 'repetition')
        for value in ('а', 'ааа', 'ха', 'хаха', 'lol', 'hello'):
            self.assertIsNone(classify_gibberish(value))

    def test_names_words_foreign_languages_and_typos_stay_normal(self):
        values = [
            'Нуркен', 'Дина', 'Александр', 'Константинополь', 'Станислав',
            'Christopher', 'Szczepanski', 'Jean-Pierre', 'František',
            'электроэнцефалографический', 'достопримечательности',
            'counterrevolutionaries', 'pneumonoultramicroscopicsilicovolcanoconiosis',
            'rhythms', 'strengths', 'ctvrthrst', 'zdravstvuyte', 'spasibo',
            'программироване', 'интерент', 'превет', 'abcdefghijklmno',
            'bonjour', 'guten tag', 'こんにちは', '你好', 'сәлеметсіз бе', 'مرحبا',
            'меня зовут впжтьеузшприекщгиек9хгщитеу0хщитк9хещрит9зек',
            'hello asdkjfh89', 'привет ааааааа', 'ghbdtn', 'rfr ltkf',
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(classify_gibberish(value))

    def test_identifiers_addresses_math_and_code_are_not_noise(self):
        values = [
            '123123', '12345678901234567890', '17+6', 'умножь 37 на 19',
            '123e4567-e89b-12d3-a456-426614174000',
            '123e4567e89b12d3a456426614174000',
            'ae6797676d99c25f5660eb9ad7f3ad0740b18fd8e51cd8707e835e7d37bce73b',
            'https://example.com/asdkjfh89', 'asdkjfh89@example.com',
            'print("asdkjfh89")', 'user_asdkjfh89', 'AB1234567890',
            'RTX4090', 'rx7650xt', 'sk-test-asdkjfh89', 'AAAABBBBCCCC',
            'abcDEFghijk89', 'QUJDREVGR0hJSktMTU5PUA==',
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(classify_gibberish(value))

    def test_bounds_mixed_scripts_and_invalid_inputs(self):
        for value in (None, 12, '', ' ', '???', '😂😂😂', 'asdkжфцтл9',
                      'фжцтлк\nasdkjfh89', 'ф' * 513):
            self.assertIsNone(classify_gibberish(value))

if __name__ == '__main__':
    unittest.main()
