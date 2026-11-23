import decimal
import unittest

from arena.arithmetic import is_arithmetic_request, parse_arithmetic
from arena.engine import calculate


class ArithmeticLanguageChecks(unittest.TestCase):
    def result(self, text):
        expression = parse_arithmetic(text)
        self.assertIsNotNone(expression, text)
        return calculate(expression)

    def test_general_commands_with_arbitrary_literals(self):
        cases = {
            'умножь 12 на 7': '84', 'Умножить 37 на 19': '703',
            'помножь 123 45': '5535', 'раздели 144 на 12': '12',
            'подели 100 на 8': '12.5', 'делить 49 на 7': '7',
            'сложи 15 и 7': '22', 'сложи 2 и 3 и 4': '9',
            'прибавь к 20 8': '28', 'прибавь 8 к 20': '28',
            'к 20 прибавь 8': '28', 'из 20 вычти 8': '12',
            'вычти 8 из 20': '12', 'отними 8 от 20': '12',
            'от 20 отними 8': '12', '17 умножить на 6': '102',
            '12 умножь на 7': '84', '144 раздели на 12': '12',
            'сколько 17 плюс 6': '23', 'сколько 17+6?': '23',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.result(text), expected)

    def test_spelled_numbers_generalize_and_keep_order(self):
        cases = {
            'двадцать три плюс шесть': '29',
            'сто сорок два минус восемьдесят семь': '55',
            'две тысячи пятьсот разделить на пять': '500',
            'два миллиарда плюс семь миллионов триста тысяч': '2007300000',
            'сложи один миллион и восемь': '1000008',
            'вычти восемь из двадцати': '12',
            'к двадцати трем прибавь шесть': '29',
            'минус семь умножить на минус три': '21',
            'девятьсот девяносто девять миллионов плюс один': '999000001',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.result(text), expected)

    def test_fractions_signs_and_precedence(self):
        cases = {
            'сколько будет 0,1 плюс 0,2?': '0.3',
            'Посчитай: (18 + 7) * 4': '100',
            '12 + 3 * 4': '24', '12 + -3': '9', '.5 + 1': '1.5',
            'два целых пять десятых плюс ноль целых пять сотых': '2.55',
            'три запятая ноль пять минус один': '2.05',
            'полтора умножить на два': '3',
            '7//3': '2', '-7%3': '2', '2**3': '8',
            'пожалуйста, умножь 12 на 7': '84',
            'сколько будет минус пять': '-5',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.result(text), expected)

    def test_does_not_extract_from_unrelated_or_incomplete_text(self):
        invalid = (
            'я сделал 2 + 3 задания вчера', 'Мне 23', '23', 'сто',
            'умножь это на то', '2 плюс', '12 на 7', 'сколько будет 2 + 3 и почему',
            'скажи другу умножь 2 на 3', '__import__("os")', '2 + foo',
            'двадцать тридцать плюс два', 'два миллиона миллион плюс один',
            'две тысячи миллион плюс один', 'три пять плюс два',
            'умножь 2 на 3 на 4', 'из 20 вычти', 'сложи 2 и',
            'прибавь к сто двадцать три', '2 + 3? а потом поговорим',
            'сколько людей завтра', 'сколько 17+6 и почему',
            '2 + (3', '2 + 3; print(4)', '1 + ' * 400, None,
        )
        for text in invalid:
            with self.subTest(text=text):
                self.assertIsNone(parse_arithmetic(text))

    def test_zero_division_and_calculator_limits_are_not_guessed(self):
        expression = parse_arithmetic('раздели десять на ноль')
        self.assertIsNotNone(expression)
        with self.assertRaises((decimal.DecimalException, ZeroDivisionError)):
            calculate(expression)
        self.assertIsNotNone(parse_arithmetic('2**1000000000'))
        with self.assertRaises(ValueError):
            calculate(parse_arithmetic('2**1000000000'))

    def test_large_literals_preserved_for_bounded_calculator(self):
        expression = parse_arithmetic('999999999999999999999 плюс 1')
        self.assertEqual(expression, '999999999999999999999+1')
        self.assertIsNone(parse_arithmetic('1' * 250 + '+1'))

    def test_attempt_detection_for_clarification(self):
        for text in ('Умножь', 'умножь это на то', 'двадцать три плюс', '12 +',
                     'из 20 вычти', 'пожалуйста, раздели пять на ноль',
                     'сколько будет 12 плюс', 'сколько 17 плюс',
                     'добавь 3 к 4', 'реши пример 2+2'):
            with self.subTest(text=text):
                self.assertTrue(is_arithmetic_request(text))
        for text in ('Я учусь умножать', 'Привет', 'Мне 23', 'Я посчитал деньги',
                     'сколько будет градусов завтра', 'реши проблему с интернетом',
                     'сколько людей завтра', 'Минус в вычислениях постоянно теряю',
                     'добавь музыку', 'посчитай слова в этом предложении'):
            with self.subTest(text=text):
                self.assertFalse(is_arithmetic_request(text))


if __name__ == '__main__':
    unittest.main()
