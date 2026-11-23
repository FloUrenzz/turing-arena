import unittest

from arena.fuzzy_tokens import TokenMatcher, bounded_edit_distance, normalize_fuzzy


class FuzzyTokenChecks(unittest.TestCase):
    def test_surface_normalization_keeps_order_negation_and_numbers(self):
        self.assertEqual(normalize_fuzzy('Щас я не нашёл 2 ключа, а вчера было −17,5'),
                         ['сейчас', 'я', 'не', 'нашел', '2', 'ключа', 'а', 'вчера', 'было', '-17,5'])
        self.assertEqual(normalize_fuzzy('Чё, ПЖ, ничего не меняй!'),
                         ['что', 'пожалуйста', 'ничего', 'не', 'меняй'])
        self.assertEqual(normalize_fuzzy('17 + 6 / -2'), ['17', '+', '6', '/', '-2'])

    def test_literals_are_opaque_and_broken_quotes_are_not_rewritten(self):
        self.assertEqual(normalize_fuzzy('Переведи «Я НИЧЁ не знаю»'),
                         ['переведи', '«Я НИЧЁ не знаю»'])
        self.assertEqual(normalize_fuzzy('Что значит "ЩАС"?'), ['что', 'значит', '"ЩАС"'])
        broken = 'Переведи «Я НИЧЁ'
        self.assertEqual(normalize_fuzzy(broken), [broken])

    def test_bounded_distance_handles_keyboard_transpositions(self):
        for left, right in [('интерент', 'интернет'), ('экзамне', 'экзамен'),
                            ('подключени', 'подключение'), ('заблы', 'забыл')]:
            self.assertEqual(bounded_edit_distance(left, right, 1), 1)
            self.assertEqual(bounded_edit_distance(right, left, 1), 1)
        self.assertEqual(bounded_edit_distance('abc', 'abc', 0), 0)
        self.assertIsNone(bounded_edit_distance('abc', 'axc', 0))
        self.assertIsNone(bounded_edit_distance('abc', 'xyz', 2))
        self.assertEqual(bounded_edit_distance('', 'ab', 2), 2)

    def test_unique_typos_have_traceable_corrections(self):
        matcher = TokenMatcher({'интернет': 20, 'экзамен': 10, 'подключение': 2, 'забыл': 1})
        corrected, changes = matcher.correct(['интерент', 'экзамне', 'подключени', 'заблы'])
        self.assertEqual(corrected, ['интернет', 'экзамен', 'подключение', 'забыл'])
        self.assertEqual(changes, [('интерент', 'интернет'), ('экзамне', 'экзамен'),
                                   ('подключени', 'подключение'), ('заблы', 'забыл')])

    def test_known_words_ambiguity_short_tokens_and_protected_entities(self):
        matcher = TokenMatcher({'кот': 100, 'кит': 1, 'пуст': 50, 'пост': 3,
                                'мост': 1, 'Нуркен': 8, 'Анкара': 9}, protected={'Нуркен'})
        tokens = ['кот', 'кит', 'пист', 'кыт', 'нуркне', 'анкра', 'нет', 'не', '17', '-17']
        self.assertEqual(matcher.correct(tokens), (tokens, []))
        # Frequency does not resolve a genuinely ambiguous spelling.
        self.assertEqual(TokenMatcher({'пост': 1000, 'пуст': 1}).correct(['пист']), (['пист'], []))

    def test_two_edits_require_long_anchored_unambiguous_words(self):
        matcher = TokenMatcher(['программирование', 'экзамен'])
        self.assertEqual(matcher.correct(['прогрмирование'])[0], ['программирование'])
        self.assertEqual(matcher.correct(['экзомон']), (['экзомон'], []))
        self.assertEqual(matcher.correct(['брагрммирование']), (['брагрммирование'], []))
        ambiguous = TokenMatcher(['программирование', 'программарование'])
        # Both candidates differ by one letter from this unknown spelling.
        self.assertEqual(ambiguous.correct(['программорование']), (['программорование'], []))

    def test_correction_never_touches_literals_or_numeric_tokens(self):
        matcher = TokenMatcher(['экзамен', 'интернет', 'нет'])
        tokens = ['«экзамне»', '"интерент"', '17', '-17', '+2', '2,5', 'нет', 'не', 'ничего']
        self.assertEqual(matcher.correct(tokens), (tokens, []))


if __name__ == '__main__':
    unittest.main()
