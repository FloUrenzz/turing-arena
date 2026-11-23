from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from arena.corpus import Corpus
from arena.corpus_import import build_corpus
from arena.data import ensure_demo_database
from arena.engine import generate
from arena.models import apply_reply, initial_state
from arena.runtime import Runtime


ROOT = Path(__file__).resolve().parents[1]


class CorpusChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = Path(cls.folder.name) / "dialogue.sqlite3"
        build_corpus((ROOT / "datasets").glob("*.xlsx"), cls.path)
        cls.corpus = Corpus(cls.path)
        cls.db = ensure_demo_database()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def reply(self, question, state=None):
        return generate(question, state or initial_state(), self.db, corpus_path=self.path)

    def test_team_answer_and_lexical_paraphrase(self):
        self.assertEqual(self.reply("Привет, как дела?")["text"], "Привет, норм, сам как?")
        self.assertEqual(self.reply("Что делаешь?")["text"], "Да ничё особенного. А ты?")
        self.assertEqual(self.reply("Я наконец сдал экзамен!")["text"], "О имба, поздравляю")

    def test_pending_answers_never_used(self):
        self.assertIsNone(self.corpus.match("Не могу найти ключи, хотя точно принёс их домой"))
        self.assertNotEqual(self.reply("Вчера переехал в новую квартиру")["intent"], "corpus")
        connection = sqlite3.connect(self.path)
        try:
            pending = connection.execute("SELECT prompt FROM corpus_replies WHERE approved=0").fetchall()
        finally:
            connection.close()
        for (question,) in pending:
            result = self.corpus.match(question)
            if result:
                self.assertEqual(result["source"], "Turing-Arena-утверждено.xlsx")

    def test_context_requires_previous_turn_and_speaker(self):
        self.assertIsNone(self.corpus.match("Вроде нормально"))
        state = initial_state()
        q = "Я сегодня сдал экзамен."
        state = apply_reply(state, q, self.reply(q))
        self.assertEqual(self.reply("Вроде нормально", state)["text"], "О, имба. Что за предметы были?")
        wrong = [{"question": "Как дела?", "text": q}]
        self.assertIsNone(self.corpus.match("Вроде нормально", wrong))
        state = apply_reply(state, "Совсем другая тема", self.reply("Совсем другая тема"))
        self.assertIsNone(self.corpus.match("Вроде нормально", state["history"]))

    def test_negation_roles_times_numbers_and_new_relation(self):
        for question in ("Я не сдал экзамен", "У моего друга сегодня выходной",
                         "У меня завтра выходной", "Давай встретимся в восемь",
                         "Почему я наконец сдал экзамен?", "Что такое база данных и сколько она стоит?",
                         "Почему лёд не плавает в воде?", "Почему лёд плавает в бензине?",
                         "Друг говорит: «Я наконец-то сдал экзамен»"):
            with self.subTest(question=question):
                self.assertIsNone(self.corpus.match(question))

    def test_static_memory_and_persona_not_copied(self):
        state = initial_state()
        question = "Меня зовут Арман"
        state = apply_reply(state, question, self.reply(question))
        self.assertIn("Арман", self.reply("Как меня зовут?", state)["text"])
        self.assertNotIn("Дина", self.reply("Помнишь, как меня зовут?", state)["text"])
        self.assertIsNone(self.corpus.match("Какую я выбрал?"))
        self.assertIsNone(self.corpus.match("Тайвань это город Китая"))
        self.assertIn("чай", self.reply("Ты чай или кофе больше любишь?")["text"].lower())
        self.assertNotEqual(self.reply("Сколько будет 17 умножить на 6?")["intent"], "corpus")
        self.assertEqual(self.reply("Сколько будет 19 умножить на 7?")["text"], "133.")

    def test_audit_rejects_changed_qualifiers_and_event_order(self):
        for question in ("Почему летом на улице телефон быстрее садится?",
                         "Почему сначала слышен гром, а потом видна молния?",
                         "Почему чай в узкой чашке быстрее остывает?",
                         "Завтра не экзамен, а я почти не готовился",
                         "Друг помог мне с проектом, я хочу отблагодарить маму"):
            with self.subTest(question=question):
                self.assertIsNone(self.corpus.match(question))
                self.assertTrue(self.reply(question)["fallback"])

    def test_offline_and_output_limits_for_all_approved_prompts(self):
        connection = sqlite3.connect(self.path)
        try:
            questions = [row[0] for row in connection.execute("SELECT prompt FROM corpus_replies WHERE approved=1")]
        finally:
            connection.close()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")):
            for question in questions:
                reply = self.reply(question)
                self.assertTrue(reply["text"].strip())
                self.assertLessEqual(len(reply["text"].encode("utf-16-le")) // 2, 300)

    def test_real_spawn_receives_corpus_and_commits_once(self):
        runtime = Runtime(self.db, timed=False, corpus_path=self.path)
        delivered = []
        first = runtime.respond("Привет, как дела?", request_id="greeting", sink=delivered.append)
        again = runtime.respond("Привет, как дела?", request_id="greeting", sink=delivered.append)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["intent"], "corpus")
        self.assertTrue(again["duplicate"])
        self.assertEqual(len(delivered), 1)


if __name__ == "__main__":
    unittest.main()
