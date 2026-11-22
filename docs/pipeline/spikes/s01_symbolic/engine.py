import ast
import operator
import re
import sqlite3
from collections import deque


def normalize(text):
    return text.lower().replace('ё', 'е')


def calculate(expression):
    if len(expression) > 100:
        raise ValueError('too long')
    tree = ast.parse(expression, mode='eval')
    if len(list(ast.walk(tree))) > 40:
        raise ValueError('too complex')
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and abs(node.value) <= 1e12:
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            value = ops[type(node.op)](visit(node.left), visit(node.right))
            if abs(value) > 1e12:
                raise ValueError('too large')
            return value
        raise ValueError('unsupported')
    return visit(tree.body)


class Bot:
    def __init__(self, db_path):
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.history = deque(maxlen=30)
        self.last = None
        self.user_name = None
        self.user_likes = {}
        self.first_question = None

    def answer(self, question):
        result = self.prepare(question)
        self.commit(question, result)
        return result

    def commit(self, question, result):
        if self.first_question is None:
            self.first_question = question[:4000]
        updates = result.get('_updates', {})
        if 'name' in updates:
            self.user_name = updates['name']
        self.user_likes.update(updates.get('likes', {}))
        self.history.append((question, dict(result)))
        if result['concepts'] and not result['fallback']:
            self.last = result['concepts'][-1]

    def prepare(self, question):
        original = question[:4000]
        full = normalize(original)
        # A preceding statement is context, not the subject of the final question.
        clauses = re.split(r'[,;.!]\s*(?:а\s+|но\s+)?(?=\S)', full)
        q = next((part.strip() for part in reversed(clauses) if part.strip()), full)
        updates = {'likes': {}}
        name_match = re.search(r'меня зовут\s+([А-ЯЁа-яё-]+)', original, re.I)
        if name_match and not re.search(r'как меня зовут', full):
            updates['name'] = name_match[1]
        for statement in re.finditer(r'\bя\s+(не\s+)?люблю\s+([^,;.!?]+)', full):
            for word in re.findall(r'[а-я]+', statement[2]):
                row = self.db.execute('SELECT concept FROM forms WHERE form=?',(word,)).fetchone()
                if row:
                    updates['likes'][row[0]] = -1 if statement[1] else 1
        tokens = re.findall(r'[а-яa-z]+|\d+', q)
        concepts = []

        def lookup_words(text):
            found = []
            for token in re.findall(r'[а-яa-z]+', text):
                row = self.db.execute('SELECT concept FROM forms WHERE form=?',(token,)).fetchone()
                if row and row[0] not in found:
                    found.append(row[0])
            return found
        for token in tokens:
            row = self.db.execute('SELECT concept FROM forms WHERE form=?',(token,)).fetchone()
            if row and row[0] not in concepts:
                concepts.append(row[0])

        def out(text, intent, facts=(), fallback=False):
            return dict(text=text[:300], intent=intent, concepts=list(concepts), facts=list(facts), fallback=fallback, _updates=updates)

        if len(question) > 4000:
            return out('Слишком много всего сразу. Можешь спросить покороче?', 'unknown', fallback=True)
        if not tokens:
            return out('Кажется, вопрос не дошёл. Повторишь?', 'unknown', fallback=True)
        if re.search(r'как меня зовут|мое имя|помнишь мое имя', q):
            return out('Ты представился как ' + self.user_name + '.' if self.user_name else 'Ты пока не представлялся.', 'recall')
        if name_match and '?' not in original and len(clauses) == 1:
            return out('Приятно познакомиться, ' + name_match[1] + '.', 'greeting')
        if re.search(r'что я (?:не )?люблю|что мне нравится|мои предпочтения|помнишь.*я люблю|помнишь обо мне|что я предпочитаю', q):
            if not self.user_likes:
                return out('Ты ещё не рассказывал мне о своих предпочтениях.', 'recall')
            phrases = []
            for cid, value in self.user_likes.items():
                row = self.db.execute('SELECT acc FROM concepts WHERE id=?',(cid,)).fetchone()
                if row:
                    phrases.append(('любишь ' if value > 0 else 'не любишь ') + row[0])
            return out('Ты говорил, что ' + ', '.join(phrases) + '.', 'recall')
        if re.search(r'перв\w* вопрос|самом начале', q):
            return out('Первым был вопрос: «' + self.first_question[:220] + '».', 'recall') if self.first_question else out('Это наш первый вопрос.', 'recall')
        if re.search(r'что (ты )?(сказал|ответил)|повтори (свой )?ответ', q):
            return out(self.history[-1][1]['text'], 'recall', self.history[-1][1]['facts']) if self.history else out('Я ещё ничего не отвечал.', 'recall')
        if re.search(r'сколько букв|переверни|задом наперед|наоборот', q):
            match = re.search(r'[«"\']([^»"\']+)[»"\']', question)
            if not match:
                match = re.search(r'(?:слове|слово)\s+([А-ЯЁа-яё-]+)', question, re.I)
            if match:
                word = match[1]
                return out(str(sum(ch.isalpha() for ch in word)) + '.' if 'букв' in q else word[::-1] + '.', 'text')
        expression = full
        for a,b in [('умножить на','*'),('разделить на','/'),('плюс','+'),('минус','-'),('×','*'),('÷','/')]:
            expression = expression.replace(a,b)
        math = re.search(r'[+\-(\s]*\d[\d\s.,+*/%()\-]*', expression)
        if math and any(s in math[0] for s in '+-*/%') and re.search(r'сколько|посчитай|вычисли|равно|^\s*[-+]?\d', q):
            try:
                value = calculate(math[0].strip().replace(',','.'))
                return out(f'{value:g}.', 'math')
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
                return out('Не могу корректно посчитать это выражение.', 'math', fallback=True)
        if re.search(r'как тебя зовут|твое имя|как к тебе обращаться|как тебя называть', q):
            row = self.db.execute("SELECT * FROM facts WHERE subject='self' AND predicate='name'").fetchone()
            return out(row['object'] + '.', 'identity', [row['id']]) if row else out('Пока не представлялся.', 'identity', fallback=True)
        if re.search(r'ты (бот|человек|робот)|кто ты|ты студент|чем занимаешься|расскажи о себе|кем (работаешь|учишься)',q):
            row = self.db.execute("SELECT * FROM facts WHERE subject='self' AND predicate='role'").fetchone()
            return out('Я ' + row['object'] + '.', 'identity', [row['id']]) if row else out('Не знаю, с чего начать.', 'identity', fallback=True)
        if re.search(r'^(привет|здравствуй|добрый день)',q):
            return out('Привет! Что обсудим?', 'greeting')
        definition = re.search(r'что такое|дай определение|что значит|объясни слово', q)
        if definition:
            if len(concepts) == 1:
                row = self.db.execute('SELECT definition FROM concepts WHERE id=?',(concepts[0],)).fetchone()
                return out(row[0], 'definition')
            return out('Не знаю точного определения. Не хочу выдумывать.', 'definition', fallback=True)
        # A first-person question refers to the interlocutor, not the persona.
        if re.search(r'\b(я|мне|мой|моя|он|она|ему|ей)\b', q) and not re.search(r'\b(ты|тебе|твой)\b',q):
            if updates['likes'] and '?' not in original:
                return out('Запомню: это твои предпочтения.', 'acknowledgment')
            return out('За другого человека я бы не решал. А ты сам как считаешь?', 'unknown', fallback=True)
        reason = bool(re.search(r'почему|зачем|чем нравится|за что любишь|по какой причине|из-за чего|чем .*привлекает|что .*привлекает',q))
        preference = bool(re.search(r'любишь|любите|нравится|нравятся|предпочитаешь|отношение|относишься|по душе|ненавидишь|любимый|любимая|любимое|любимые|увлекаешься',q))
        choice = bool(re.search(r'\bили\b|выберешь|выбираешь|лучше|предпочтешь',q))
        if 'или' in tokens:
            alternatives = re.split(r'\bили\b', q)
            if any(len(lookup_words(part)) != 1 for part in alternatives):
                return out('Не все варианты понял. Не хочу выбирать наугад.', 'choice', fallback=True)
        category = None
        for pattern, candidate in [(r'напит|пьешь|пить','drink'),(r'слушаешь|слушать','listen'),(r'занятие|делать|свободное время|увлечен','activity'),(r'еда|блюдо|кушать','food'),(r'животн','animal'),(r'время года','season')]:
            if re.search(pattern,q):
                category = candidate
                break
        if category and re.search(r'пьешь|слушаешь|увлекаешься', q):
            preference = True
        if category and not concepts:
            row = self.db.execute("SELECT f.* FROM facts f JOIN groups g ON f.object=g.concept WHERE f.subject='self' AND f.predicate='likes' AND g.category=? ORDER BY f.value DESC,f.id LIMIT 1",(category,)).fetchone()
            if row:
                concepts.append(row['object'])
                preference = True
        if preference and not concepts and not category and re.search(r'что\b|чем\b',q):
            row = self.db.execute("SELECT * FROM facts WHERE subject='self' AND predicate='likes' AND value>0 ORDER BY value DESC,id LIMIT 1").fetchone()
            if row:
                concepts.append(row['object'])
        if choice and len(concepts) < 2:
            return out('Не со всеми вариантами знаком, поэтому выбирать наугад не буду.', 'choice', fallback=True)
        if not concepts and self.last and (reason or re.search(r'^(а ты|тоже|а почему)',q)):
            concepts.append(self.last)
        if choice and len(concepts) >= 2:
            scored = []
            for cid in concepts:
                fact = self.db.execute("SELECT * FROM facts WHERE subject='self' AND predicate='likes' AND object=?",(cid,)).fetchone()
                if fact is None:
                    return out('Не уверен: не со всем из этого знаком.', 'choice', fallback=True)
                scored.append(fact)
            chosen = max(scored, key=lambda f:f['value'])
            if chosen['value'] < 0:
                return out('Из этих вариантов ничего особо не хочется.', 'choice', [f['id'] for f in scored])
            noun = self.db.execute('SELECT acc FROM concepts WHERE id=?',(chosen['object'],)).fetchone()[0]
            concepts[:] = [chosen['object']]
            return out('Я бы выбрал ' + noun + '.', 'choice', [chosen['id']])
        if concepts and (reason or preference or re.match(r'^а\s+',q)):
            if len(concepts) > 1:
                return out('Ты про что-то одно или про всё вместе?', 'unknown', fallback=True)
            cid = concepts[0]
            fact = self.db.execute("SELECT * FROM facts WHERE subject='self' AND predicate='likes' AND object=?",(cid,)).fetchone()
            if not fact:
                return out('Пока нет определённого мнения об этом.', 'preference', fallback=True)
            noun = self.db.execute('SELECT acc FROM concepts WHERE id=?',(cid,)).fetchone()[0]
            negative = bool(re.search(r'\bне\s+(?:очень\s+)?(?:любишь|нравится|нравятся)|ненавидишь',q))
            positive = fact['value'] > 0
            correction = negative == positive and preference
            statement = ('люблю ' if positive else 'не очень люблю ') + noun + '.'
            if reason:
                return out(('Вообще-то я ' + statement + ' ' if correction else '') + fact['reason'], 'reason', [fact['id']])
            prefix = 'Вообще-то я ' if correction else 'Я '
            return out(prefix + statement, 'preference', [fact['id']])
        if reason:
            return out('Ты про какую часть моего ответа?', 'reason', fallback=True)
        return out('Сходу не знаю, что ответить. Можешь уточнить вопрос?', 'unknown', fallback=True)
