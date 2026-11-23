from pathlib import Path
import unittest

from arena.data import ensure_demo_database
from arena.engine import generate
from arena.introductions import parse_introduction
from arena.models import apply_reply, initial_state


ROOT = Path(__file__).resolve().parents[1]


class IntroductionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ensure_demo_database()

    def answer(self, text, state=None):
        return generate(text, state or initial_state(), self.db,
                        corpus_path=ROOT / "data/dialogue.sqlite3")

    def test_how_are_you_is_not_a_name_question(self):
        for question in ('У тебя как дела?', 'А у тебя как настроение?',
                         'У меня всё нормально, а у тебя как дела?'):
            result = self.answer(question)
            self.assertFalse(result['fallback'], question)
            self.assertNotEqual(result['intent'], 'identity', question)
            self.assertNotEqual(result['text'], 'Саша', question)
        for question in ('А тебя как?', 'Тебя как зовут?', 'Как тебя зовут?'):
            self.assertEqual(self.answer(question)['text'], 'Саша', question)

    def test_unseen_names_across_alphabets_and_word_orders(self):
        # Names deliberately not taken from any corpus or name dictionary.
        names = ("Нуркен", "Нұркен", "Әлия", "Ғалым", "Өркен", "Үміт", "Іңкәр",
                 "Zélie", "李明", "محمد", "Анна-Мария", "D’Arcy", "@m1tello", "Эллиор",
                 "आदित्य", "อารีย์", "أَحْمَد", "Анна Мария", "Иван Иванов")
        for name in names:
            for prefix in ("Меня зовут ", "Зовут меня ", "Моё имя ", "Зови меня ",
                           "Салам, меня зовут ", "Привет! Зовут меня ",
                           "Короче, меня зовут ", "Ты перепутал, моё имя "):
                with self.subTest(name=name, prefix=prefix):
                    text = prefix + name
                    reply = self.answer(text)
                    self.assertFalse(reply["fallback"])
                    self.assertEqual(reply["updates"]["user_name"], name)
                    self.assertFalse(reply["text"].endswith("."))
                    state = apply_reply(initial_state(), text, reply)
                    self.assertEqual(state["user_name"], name)
                    self.assertIn(name, self.answer("Помнишь, как меня зовут?", state)["text"])

    def test_case_punctuation_and_short_introduction(self):
        for text, expected in (("я нуркен", "Нуркен"), ("Я Нуркен", "Нуркен"),
                               ("я дмитрий", "Дмитрий"), ("я юрий", "Юрий"),
                               ("я анатолий", "Анатолий"), ("я валерий", "Валерий"),
                               ("я рая", "Рая"),
                               ("ку, я Әлия", "Әлия"), ("Моё имя: Нуркен", "Нуркен"),
                               ("Моё имя:Нуркен", "Нуркен"), ("Зови меня 'Олег'", "Олег"),
                               ('Меня зовут «Арман»', "Арман"),
                               ('Меня зовут «анна мария»', "Анна мария"),
                               ("Меня зовут Zé\u006c\u0069e", "Zélie")):
            with self.subTest(text=text):
                reply = self.answer(text)
                self.assertFalse(reply["fallback"])
                self.assertEqual(reply["updates"].get("user_name"), expected)

    def test_correction_and_recall_after_other_turns(self):
        state = initial_state()
        for text, expected in (("Я Дина", "Дина"), ("Нет, меня зовут Вера", "Вера"),
                               ("Меня зовут не Вера, а Әлия", "Әлия"),
                               ("Я не Дина, меня зовут Әлия", "Әлия"),
                               ("Я не Әлия, я Нұркен", "Нұркен")):
            reply = self.answer(text, state)
            state = apply_reply(state, text, reply)
            self.assertEqual(state["user_name"], expected)
        for text in ("Привет, как дела?", "Сколько будет 17 плюс 6?", "Что делаешь?"):
            state = apply_reply(state, text, self.answer(text, state))
        self.assertEqual(self.answer("Как меня зовут?", state)["text"], "Кнш, Нұркен же")

    def test_introduction_with_reciprocal_or_memory_question(self):
        for text in ("Меня зовут Нуркен, а тебя?", "Я Нуркен, тебя как зовут?",
                     "Салам, меня зовут Нуркен. Как тебя зовут?",
                     "Меня зовут Нуркен. Помнишь, как меня зовут?"):
            with self.subTest(text=text):
                reply = self.answer(text)
                self.assertFalse(reply["fallback"])
                state = apply_reply(initial_state(), text, reply)
                self.assertEqual(state["user_name"], "Нуркен")
                self.assertIn("Нуркен", reply["text"])

    def test_non_names_questions_and_quoted_speech_do_not_overwrite(self):
        state = apply_reply(initial_state(), "Я Нуркен", self.answer("Я Нуркен"))
        for text in ("Я устал", "я студент", "Я программист", "Я из Алматы", "Я люблю кофе",
                     "Я работаю", "Я один", "Я проспал", "Я сдал экзамен", "Я Арман?",
                     "я болею", "Я отдыхаю", "я опаздываю", "Я скучаю", "Я молодец", "Я печальный",
                     "я размышляю", "Я ПЕРЕЖИВАЮ", "я задумчивый",
                     "Меня зовут Иван или Пётр?", "Меня зовут Нуркен, да?",
                     "Моё имя редко кому знакомо", "Меня зовут необычно, мало кто такое слышал",
                     "Моё имя состоит из пяти букв", "Меня зовут ужинать", "Моё имя тебе уже известно",
                     "Меня зовут не Дина", "Меня зовут Арман?", "Как меня зовут?",
                     "Меня зовут домой", 'Друг сказал: «Меня зовут Олег»',
                     '«Меня зовут Олег»', "Если меня зовут Олег", "Моего друга зовут Олег"):
            with self.subTest(text=text):
                self.assertIsNone(parse_introduction(text))
                result = self.answer(text, state)
                self.assertNotIn("user_name", result["updates"])
                self.assertEqual(apply_reply(state, text, result)["user_name"], "Нуркен")

    def test_generation_does_not_mutate_state(self):
        state = initial_state()
        self.answer("Меня зовут Нуркен", state)
        self.assertIsNone(state["user_name"])

    def test_casual_memory_questions_and_reminder(self):
        state = apply_reply(initial_state(), "Я Нуркен", self.answer("Я Нуркен"))
        for question in ("ты запомнил мое имя", "помнишь имя?", "моё имя помнишь?", "я же представился"):
            with self.subTest(question=question):
                answer = self.answer(question, state)
                self.assertFalse(answer["fallback"])
                self.assertIn("Нуркен", answer["text"])
        for question in ("а тебя как зовут", "тебя как", "а тебя?"):
            with self.subTest(question=question):
                self.assertEqual(self.answer(question, state)["intent"], "identity")


if __name__ == "__main__":
    unittest.main()
