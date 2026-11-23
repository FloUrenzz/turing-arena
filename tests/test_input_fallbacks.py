import json
from pathlib import Path
import subprocess
import sys
import unittest

from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import initial_state, apply_reply


ROOT = Path(__file__).resolve().parents[1]


class InputFallbackChecks(unittest.TestCase):
    def test_noise_is_short_clarification_and_keeps_name(self):
        state = initial_state()
        state['user_name'] = 'Нуркен'
        for question in ('впжтьеузшприекщгиек9хгщитеу0хщитк9хещрит9зек', 'asdkjfh89'):
            reply = generate(question, state, ensure_demo_database())
            self.assertEqual(reply['text'], 'это ты случайно набрал?')
            self.assertFalse(reply['fallback'])
            self.assertEqual(apply_reply(state, question, reply)['user_name'], 'Нуркен')

    def test_normal_names_math_and_control_question_still_work(self):
        state = initial_state()
        for question, intent in (
            ('Меня зовут Нуркен', 'acknowledgment'),
            ('37 умножить на 19', 'math'),
            ('Почему после дождя иногда появляется радуга? Объясни простыми словами.', 'explanation'),
        ):
            reply = generate(question, state, ensure_demo_database())
            self.assertEqual(reply['intent'], intent)
            self.assertFalse(reply['fallback'])

    def test_real_cli_uses_russian_for_latin_noise_and_full_corpus_by_default(self):
        command = [sys.executable, '-X', 'utf8', 'main.py', '--chat', '--json', '--no-corpus']
        inputs = 'asdkjfh89\nМеня зовут Нуркен\nПомнишь как меня зовут?\n'
        result = subprocess.run(command, cwd=ROOT, input=inputs,
                                text=True, encoding='utf-8', capture_output=True, check=True, timeout=10)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(replies[0]['text'], 'это ты случайно набрал?')
        self.assertEqual(replies[2]['text'], 'Кнш, Нуркен же')
        self.assertTrue(all(reply['status'] == 'ok' and not reply['fallback'] for reply in replies))
        default = subprocess.run(command[:-1], cwd=ROOT, input='Не понял условие дамашки\n', text=True,
                                 encoding='utf-8', capture_output=True, check=True, timeout=10)
        answer = json.loads(default.stdout)
        self.assertEqual(answer['text'], 'А что именно просят сделать?')
        self.assertTrue(any('ещё-5000' in trace for trace in answer['trace']))
        help_result = subprocess.run([sys.executable, '-X', 'utf8', 'main.py', '--help'], cwd=ROOT,
                                     text=True, encoding='utf-8', capture_output=True, check=True, timeout=10)
        self.assertNotIn('--english', help_result.stdout)

    def test_topic_fallbacks_and_known_answers_have_correct_priority(self):
        state = initial_state()
        examples = (
            ('Какой состав шампуня?', 'я не изучаю составы, тут не подскажу'),
            ('Состав колы', 'я не изучаю составы, тут не подскажу'),
            ('Из чего сделан бетон?', 'я не изучаю составы, тут не подскажу'),
            ('Объясни квантовую физику', 'я в этом предмете не особо разбираюсь'),
            ('В чем смысл жизни?', 'я над таким особо не задумывался'),
        )
        for question, expected in examples:
            self.assertEqual(generate(question, state, ensure_demo_database())['text'], expected)
        for question in ('Состав команды', 'Из чего состоит наша команда?', 'Я сдал экзамен по физике'):
            self.assertNotEqual(generate(question, state, ensure_demo_database())['intent'], 'topic_fallback')
        self.assertEqual(generate('Почему после дождя появляется радуга?', state,
                                  ensure_demo_database())['intent'], 'explanation')


if __name__ == '__main__':
    unittest.main()
