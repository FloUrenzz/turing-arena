"""Strict Russian arithmetic language -> a bounded, non-executable expression."""

import ast
import re


_UNITS = {
    'ноль': 0, 'нуль': 0, 'нуля': 0, 'нулю': 0,
    'один': 1, 'одна': 1, 'одно': 1, 'одного': 1, 'одному': 1,
    'два': 2, 'две': 2, 'двух': 2, 'двум': 2,
    'три': 3, 'трех': 3, 'трем': 3, 'четыре': 4, 'четырех': 4, 'четырем': 4,
    'пять': 5, 'пяти': 5, 'шесть': 6, 'шести': 6, 'семь': 7, 'семи': 7,
    'восемь': 8, 'восьми': 8, 'девять': 9, 'девяти': 9,
}
_TEENS = {word: index for index, word in enumerate(
    'десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split(), 10)}
_TEENS.update({word[:-1] + 'и': number for word, number in list(_TEENS.items())})
_TENS = dict(zip('двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split(), range(20, 100, 10)))
_TENS.update(dict(zip('двадцати тридцати сорока пятидесяти шестидесяти семидесяти восьмидесяти девяноста'.split(), range(20, 100, 10))))
_HUNDREDS = dict(zip('сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split(), range(100, 1000, 100)))
_HUNDREDS.update(dict(zip('ста двухсот трехсот четырехсот пятисот шестисот семисот восьмисот девятисот'.split(), range(100, 1000, 100))))
_SCALES = {word: value for words, value in (
    ('тысяча тысячи тысяч тысячу', 1000),
    ('миллион миллиона миллионов', 1000000),
    ('миллиард миллиарда миллиардов', 1000000000),
) for word in words.split()}
_FRACTIONS = {word: digits for words, digits in (
    ('десятая десятых', 1), ('сотая сотых', 2), ('тысячная тысячных', 3),
    ('десятитысячная десятитысячных', 4), ('стотысячная стотысячных', 5),
    ('миллионная миллионных', 6),
) for word in words.split()}
_ALLOWED_AST = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
                ast.Pow, ast.UAdd, ast.USub)


def _small_integer(words):
    if len(words) == 1 and re.fullmatch(r'\d{1,12}', words[0]):
        return int(words[0])
    if not words:
        return None
    words = list(words)
    value = 0
    if words and words[0] in _HUNDREDS:
        value += _HUNDREDS[words.pop(0)]
    if words and words[0] in _TENS:
        value += _TENS[words.pop(0)]
        if words and words[0] in _UNITS and _UNITS[words[0]] > 0:
            value += _UNITS[words.pop(0)]
    elif words and words[0] in _TEENS:
        value += _TEENS[words.pop(0)]
    elif words and words[0] in _UNITS:
        value += _UNITS[words.pop(0)]
    return value if not words else None


def _integer(words):
    total, start, last_scale = 0, 0, 10**12
    for index, word in enumerate(words):
        if word not in _SCALES:
            continue
        scale = _SCALES[word]
        if scale >= last_scale:
            return None
        group = _small_integer(words[start:index]) if index > start else 1
        if group is None or not 1 <= group <= 999:
            return None
        total += group * scale
        last_scale, start = scale, index + 1
    rest = _small_integer(words[start:]) if start < len(words) else 0
    if rest is None or (start and rest >= last_scale):
        return None
    result = total + rest
    return result if words and result <= 10**12 else None


def _number(text):
    if re.fullmatch(r'\d{1,100}(?:[.,]\d{1,100})?', text):
        integer, dot, fraction = text.replace(',', '.').partition('.')
        return str(int(integer)) + (dot + fraction if dot else '')
    if re.fullmatch(r'[.,]\d{1,100}', text):
        return '0.' + text[1:]
    if text in ('полтора', 'полторы'):
        return '1.5'
    words = text.split()
    fraction = re.fullmatch(r'(.+?)\s+цел(?:ая|ое|ых)\s+(.+)\s+(\w+)', text)
    if fraction and fraction[3] in _FRACTIONS:
        whole, part = _integer(fraction[1].split()), _integer(fraction[2].split())
        width = _FRACTIONS[fraction[3]]
        if whole is not None and part is not None and part < 10**width:
            return str(whole) + '.' + str(part).zfill(width)
        return None
    if words.count('запятая') == 1:
        index = words.index('запятая')
        whole, fractional = _integer(words[:index]), words[index + 1:]
        if whole is None or not fractional:
            return None
        if all(word in _UNITS for word in fractional):
            digits = ''.join(str(_UNITS[word]) for word in fractional)
        else:
            value = _integer(fractional)
            if value is None:
                return None
            digits = str(value)
        return str(whole) + '.' + digits if len(digits) <= 12 else None
    value = _integer(words)
    return str(value) if value is not None else None


def _expression(text):
    for pattern, operator in (
        (r'\b(?:умножить|умножь|помножить|помножь)\s+на\b', '*'),
        (r'\b(?:разделить|раздели|делить|поделить|подели)\s+на\b', '/'),
        (r'\bплюс\b', '+'), (r'\bминус\b', '-'),
    ):
        text = re.sub(pattern, operator, text)
    result = []
    for part in re.split(r'(\*\*|//|[+*/%()\-])', text):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r'\*\*|//|[+*/%()\-]', part):
            result.append(part)
        else:
            value = _number(part)
            if value is None:
                return None
            result.append(value)
    expression = ''.join(result)
    if not expression or len(expression) > 240:
        return None
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError):
        return None
    nodes = list(ast.walk(tree))
    if len(nodes) > 40 or any(not isinstance(node, _ALLOWED_AST) for node in nodes):
        return None
    return expression


def _binary(left, right, operator):
    left, right = _expression(left.strip()), _expression(right.strip())
    return _expression(f'({left}){operator}({right})') if left and right else None


def _split_two_numbers(text):
    """A missing separator is accepted only if there is one possible split."""
    words = text.split()
    choices = [(left, right) for index in range(1, len(words))
               if (left := _number(' '.join(words[:index]))) is not None
               and (right := _number(' '.join(words[index:]))) is not None]
    return choices[0] if len(choices) == 1 else None


def is_arithmetic_request(text):
    """Recognize an attempted calculation, including an incomplete command."""
    if not isinstance(text, str):
        return False
    text = ' '.join(text.casefold().replace('ё', 'е').split())
    text = re.sub(r'^пожалуйста[, ]+', '', text)
    if re.match(r'^(?:а\s+)?(?:умножь|умножить|помножь|помножить|раздели|разделить|дели|делить|'
                r'подели|поделить|сложи|сложить|вычти|вычесть|отними)\b', text):
        return True
    if re.match(r'^(?:из|от|к)\s+', text) and re.search(r'\b(?:вычти|вычесть|отними|прибавь|добавь)\b', text):
        return True
    number_words = _UNITS | _TEENS | _TENS | _HUNDREDS | _SCALES
    has_number = bool(re.search(r'\d', text)) or any(word in number_words or word in ('полтора', 'полторы') for word in text.split())
    has_operator = bool(re.search(r'[+*/%×÷]|\d\s*[-−]|\b(?:плюс|минус|умножить|разделить|делить)\b', text))
    ambiguous = re.match(r'^(?:а\s+)?(?:сколько(?:\s+(?:будет|получится))?|посчитай|вычисли|прибавь|прибавить|добавь)\b', text)
    if ambiguous:
        return has_number or text[ambiguous.end():].strip(' :?!.') == '' and text.startswith(('посчитай', 'вычисли'))
    if re.match(r'^реши\b', text):
        return bool(re.match(r'^реши\s+пример\b', text)) or has_number and has_operator
    first = text.split(' ', 1)[0]
    signed_number = first == 'минус' and has_number
    numeric_start = bool(re.match(r'^[+\-−(]*(?:\d|[.,]\d)', text)) or first in number_words or signed_number or first in ('полтора', 'полторы')
    return numeric_start and has_operator


def parse_arithmetic(text):
    """Return a safe expression or None; never select a substring of a story.

    Evaluation and division-by-zero/result limits belong to engine.calculate.
    This parser accepts at most 512 input characters and a 240-character AST.
    """
    if not isinstance(text, str) or len(text) > 512:
        return None
    text = ' '.join(text.casefold().replace('ё', 'е').split()).rstrip(' .?!')
    text = text.replace('×', '*').replace('÷', '/').replace('−', '-')
    text = re.sub(r'^пожалуйста[, ]+|[, ]+пожалуйста$', '', text).strip()
    prefix = re.match(r'^(?:а\s+)?(?:сколько(?:\s+(?:будет|получится))?|посчитай|вычисли|реши(?:\s+пример)?)(?:\s*:\s*|\s+)', text)
    explicit = bool(prefix)
    if prefix:
        text = text[prefix.end():]
    command = re.fullmatch(r'(?:умножь|умножить|помножь|помножить|раздели|разделить|дели|делить|подели|поделить)\s+(.+)', text)
    if command:
        operator = '*' if re.match(r'^(?:умнож|помнож)', text) else '/'
        operands = re.split(r'\s+(?:на|и)\s+', command[1])
        if len(operands) == 2:
            return _binary(*operands, operator)
        if len(operands) == 1:
            pair = _split_two_numbers(command[1])
            return _binary(*pair, operator) if pair else None
        return None
    command = re.fullmatch(r'(?:сложи|сложить)\s+(.+)', text)
    if command:
        values = re.split(r'\s+и\s+', command[1])
        if len(values) == 1:
            pair = _split_two_numbers(command[1])
            values = list(pair) if pair else []
        parsed = [_expression(value) for value in values]
        return _expression('+'.join(f'({value})' for value in parsed)) if len(parsed) >= 2 and all(parsed) else None
    for pattern, operator, reverse in (
        (r'(?:прибавь|прибавить|добавь)\s+(.+)\s+к\s+(.+)', '+', True),
        (r'к\s+(.+)\s+(?:прибавь|добавь)\s+(.+)', '+', False),
        (r'(?:вычти|вычесть)\s+(.+)\s+из\s+(.+)', '-', True),
        (r'из\s+(.+)\s+(?:вычти|вычесть)\s+(.+)', '-', False),
        (r'отними\s+(.+)\s+от\s+(.+)', '-', True),
        (r'от\s+(.+)\s+отними\s+(.+)', '-', False),
    ):
        command = re.fullmatch(pattern, text)
        if command:
            values = (command[2], command[1]) if reverse else (command[1], command[2])
            return _binary(*values, operator)
    command = re.fullmatch(r'(?:прибавь|добавь)\s+к\s+(.+)', text)
    if command:
        pair = _split_two_numbers(command[1])
        return _binary(*pair, '+') if pair else None
    expression = _expression(text)
    if expression is None:
        return None
    if explicit or any(isinstance(node, ast.BinOp) for node in ast.walk(ast.parse(expression, mode='eval'))):
        return expression
    return None
