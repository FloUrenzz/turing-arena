"""Conservative recognition of obvious keyboard noise, without language models.

This is not a language detector or a test of whether a word exists. Ambiguous
words, sentences, identifiers and unsupported scripts are left to the ordinary
dialogue pipeline. A false negative is preferable to mocking an unfamiliar name.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Gibberish:
    script: str
    kind: str
    has_digits: bool
    length: int


_LETTER_BLOCKS = {
    'cyrillic': re.compile(r'[а-яё]+'),
    'latin': re.compile(r'[a-z]+'),
}
_VOWELS = {'cyrillic': set('аеёиоуыэюя'), 'latin': set('aeiouy')}
_KEY_ROWS = {
    'cyrillic': ('йцукенгшщзхъ', 'фывапролджэ', 'ячсмитьбю'),
    'latin': ('qwertyuiop', 'asdfghjkl', 'zxcvbnm'),
}


def _longest_consonants(letters, script):
    longest = current = 0
    for letter in letters:
        if letter in _VOWELS[script] or letter in 'ьъ':
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def classify_gibberish(text):
    """Return Gibberish for clear single-block noise, or None when uncertain.

    Supported scripts are Russian Cyrillic and ASCII Latin. Normal foreign
    language text is never rejected merely because it is not Russian. We also
    deliberately leave capitalized names and code-like material untouched.
    """
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not 6 <= len(value) <= 512:
        return None
    # Spaces and punctuation can indicate real sentences, links, quotes or code.
    if not re.fullmatch(r'[a-zа-яё0-9]+', value):
        return None
    letters = re.sub(r'[0-9]', '', value)
    script = next((name for name, pattern in _LETTER_BLOCKS.items()
                   if pattern.fullmatch(letters)), None)
    if script is None:
        return None
    if re.fullmatch(r'[a-f0-9]{12,}', value):
        return None  # hexadecimal keys, checksums and unhyphenated UUIDs
    has_digits = bool(re.search(r'[0-9]', value))
    description = lambda kind: Gibberish(script, kind, has_digits, len(value))

    if not has_digits and len(set(letters)) == 1:
        return description('repetition')
    if not has_digits and len(value) >= 8:
        for width in (2, 3):
            unit = value[:width]
            if len(set(unit)) > 1 and len(value) >= width * 4 and value == (unit * len(value))[:len(value)]:
                return description('repetition')

    # Whole keyboard-row walks are stronger evidence than vowel statistics.
    for row in _KEY_ROWS[script]:
        for walk in (row, row[::-1]):
            if len(letters) >= 6 and letters in walk:
                return description('keyboard')

    unique = len(set(letters))
    if unique < 5 or len(letters) < 7:
        return None
    vowels = sum(letter in _VOWELS[script] for letter in letters)
    consonants = _longest_consonants(letters, script)
    # E.g. "asdkjfh89": a consonant cluster plus digits, not just an unknown word.
    if has_digits and consonants >= 5 and vowels / len(letters) < .20:
        return description('noise')
    # Interleaved digits distinguish the user's long random example from a word.
    digit_runs = list(re.finditer(r'[0-9]+', value))
    internal_runs = sum(run.start() > 0 and run.end() < len(value) for run in digit_runs)
    if len(value) >= 20 and unique >= 8 and internal_runs >= 3:
        return description('noise')
    # Pure-letter input needs much stronger evidence. Common long words and
    # transliteration have vowels; a lone short consonant word is inconclusive.
    if len(letters) >= 12 and unique >= 7 and consonants >= 8 and vowels / len(letters) < .15:
        return description('noise')
    return None
