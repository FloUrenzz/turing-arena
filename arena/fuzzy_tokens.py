"""Small, offline surface-token helpers for approximate corpus retrieval.

``normalize_fuzzy`` deliberately does not stem, discard negation, or reorder text.
Quoted spans remain opaque. ``TokenMatcher`` corrects unknown spelling only; it
does not choose meanings, infer named entities, or break ties by word frequency.
Pass known names/entities in ``protected`` when building the corpus vocabulary.
"""

from functools import lru_cache
import re
import unicodedata


_ALIASES = {
    'че': 'что', 'чо': 'что', 'щас': 'сейчас', 'ща': 'сейчас',
    'ниче': 'ничего', 'ничо': 'ничего', 'нормас': 'нормально',
    'пж': 'пожалуйста', 'плиз': 'пожалуйста', 'спс': 'спасибо',
    'кнш': 'конечно', 'седня': 'сегодня', 'сення': 'сегодня',
}
_LITERAL = re.compile(r'«[^»]*»|"[^"]*"|“[^”]*”|‘[^’]*’|`[^`]*`|\'[^\']*\'')
_QUOTES = set('«»"“”‘’`\'')
_TOKEN = re.compile(r'[+\-−]?\d+(?:[.,]\d+)?|[^\W\d_]+(?:[-’\'][^\W\d_]+)*|[+*/%=<>−-]', re.UNICODE)
_WORD = re.compile(r'[а-яa-z]{4,40}')
_PROTECTED = set('''
не нет ни без никогда никто ничего ничто никак некуда незачем негде нигде никуда
я ты он она мы вы они меня тебя ему ей мне тебе нас вас им его ее их
сегодня вчера завтра сейчас потом сначала раньше позже всегда иногда постоянно
алматы алмата алма-ата астана казахстан казахстана казахстане китай китая китае китаю
тайвань тайваня тайване тайванем турция турции стамбул анкара байкал антарктида
москва москве россия россии дубай дубае европа азия америка африка
'''.split())


def _fold(text):
    return unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е').replace('−', '-')


def normalize_fuzzy(text):
    """Return ordered surface tokens, preserving literals and signed quantities.

    Ordinary punctuation is omitted: the caller must keep speech-act and clause
    guards from the original input. Arithmetic operators stay separate tokens.
    An unmatched quote returns one opaque token instead of modifying its content.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    quoted = list(_LITERAL.finditer(text))
    remainder = _LITERAL.sub('', text)
    if any(character in _QUOTES for character in remainder):
        return [text]
    result, end = [], 0

    def add_words(fragment):
        for match in _TOKEN.finditer(_fold(fragment)):
            token = match[0]
            result.append(_ALIASES.get(token, token))

    for match in quoted:
        add_words(text[end:match.start()])
        result.append(match[0])
        end = match.end()
    add_words(text[end:])
    return result


def bounded_edit_distance(left, right, max_distance=1):
    """Bounded Damerau/OSA distance; one adjacent transposition costs one edit.

    Return ``None`` if the threshold is exceeded. OSA is sufficient for isolated
    keyboard typos; this function does not perform unrestricted string rewriting.
    """
    if not isinstance(left, str) or not isinstance(right, str):
        raise TypeError('Edit-distance operands must be strings')
    if max_distance not in (0, 1, 2):
        raise ValueError('Only edit distances 0, 1 and 2 are supported')
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_distance or max_distance == 0:
        return None
    if not left or not right:
        result = max(len(left), len(right))
        return result if result <= max_distance else None
    previous_previous = None
    previous = list(range(len(right) + 1))
    for index, left_character in enumerate(left, 1):
        current = [index] + [max_distance + 1] * len(right)
        lower = max(1, index - max_distance)
        upper = min(len(right), index + max_distance)
        for column in range(lower, upper + 1):
            current[column] = min(
                previous[column] + 1,
                current[column - 1] + 1,
                previous[column - 1] + (left_character != right[column - 1]),
            )
            if (previous_previous is not None and column > 1
                    and left_character == right[column - 2]
                    and left[index - 2] == right[column - 1]):
                current[column] = min(current[column], previous_previous[column - 2] + 1)
        if min(current[lower:upper + 1], default=max_distance + 1) > max_distance:
            return None
        previous_previous, previous = previous, current
    result = previous[-1]
    return result if result <= max_distance else None


class TokenMatcher:
    """Conservative spelling corrections against an immutable surface vocabulary.

    ``vocabulary`` may be an iterable of words or a document-frequency mapping.
    ``protected`` contains names, entities and other terms that must never be
    corrected or offered as a correction. Numbers, literals, short words and
    built-in semantic markers are always protected. Existing vocabulary tokens
    stay unchanged, even if another word is more frequent.

    ``correct(tokens)`` returns ``(corrected_tokens, [(original, replacement)])``.
    Corrections with two edits additionally require length >= 8 and unchanged
    first three / last two characters. Ambiguous nearest matches are left alone.
    """

    def __init__(self, vocabulary, protected=()):
        self.vocabulary = frozenset(_fold(word) for word in vocabulary if isinstance(word, str))
        self.protected = frozenset(_PROTECTED | {_fold(word) for word in protected})
        self._deletions = {}
        self._anchored = {}
        for word in self.vocabulary:
            if not _WORD.fullmatch(word) or word in self.protected:
                continue
            for deletion in {word[:index] + word[index + 1:] for index in range(len(word))}:
                self._deletions.setdefault(deletion, set()).add(word)
            if len(word) >= 8:
                self._anchored.setdefault((word[:3], word[-2:], len(word)), set()).add(word)
        # Per-instance cache avoids retaining every previously built vocabulary.
        self._correct_word = lru_cache(maxsize=4096)(self._find_correction)

    def __getstate__(self):
        # multiprocessing spawn transfers a trusted in-memory search snapshot.
        # The per-process LRU is disposable; all vocabulary indexes are retained.
        state = dict(self.__dict__)
        state.pop('_correct_word', None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._correct_word = lru_cache(maxsize=4096)(self._find_correction)

    def _find_correction(self, word):
        if word in self.vocabulary or word in self.protected or not _WORD.fullmatch(word):
            return word
        candidates = set(self._deletions.get(word, ()))
        for index in range(len(word)):
            deletion = word[:index] + word[index + 1:]
            if deletion in self.vocabulary and deletion not in self.protected and _WORD.fullmatch(deletion):
                candidates.add(deletion)
            candidates.update(self._deletions.get(deletion, ()))
        nearest = {candidate for candidate in candidates
                   if bounded_edit_distance(word, candidate, 1) == 1}
        if nearest:
            return next(iter(nearest)) if len(nearest) == 1 else word
        if len(word) < 8:
            return word
        for length in range(max(8, len(word) - 2), len(word) + 3):
            candidates.update(self._anchored.get((word[:3], word[-2:], length), ()))
        nearest = {candidate for candidate in candidates
                   if len(candidate) >= 8 and candidate[:3] == word[:3]
                   and candidate[-2:] == word[-2:]
                   and bounded_edit_distance(word, candidate, 2) == 2}
        return next(iter(nearest)) if len(nearest) == 1 else word

    def correct(self, tokens):
        corrected, changes = [], []
        for token in tokens:
            replacement = self._correct_word(token)
            corrected.append(replacement)
            if replacement != token:
                changes.append((token, replacement))
        return corrected, changes
