from pathlib import Path
from contextlib import closing
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


class ReviewedCorpusChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = Path(cls.folder.name) / "reviewed.sqlite3"
        cls.counts = build_corpus((ROOT / "datasets").glob("*.xlsx"), cls.path,
                                 review_path=ROOT / "data/corpus_review.json")
        cls.corpus = Corpus(cls.path)
        cls.db = ensure_demo_database()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def reply(self, question, state=None):
        return generate(question, state or initial_state(), self.db, corpus_path=self.path)

    def test_complete_review_and_pending_activation_provenance(self):
        self.assertEqual(self.counts["rows"], 350)
        self.assertEqual(self.counts["approved"], 296)
        self.assertEqual(self.counts["review_held"], 54)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM corpus_reviews").fetchone()[0], 350)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM corpus_replies WHERE status='Проверить' AND approved=1").fetchone()[0], 176)
            record = connection.execute("SELECT r.answer,v.original_answer FROM corpus_replies r JOIN corpus_reviews v ON v.reply_id=r.id WHERE r.example_id='194'").fetchone()
            self.assertEqual(record, ("Какого цвета было небо?", "Скинь, интересно посмотреть"))
        reply = self.reply("Не могу найти ключи, хотя точно принёс их домой")
        self.assertEqual(reply["text"], "В карманах и сумке смотрел?")
        self.assertIn("review=accept", reply["trace"][0])

    def test_real_context_starters_and_followups(self):
        for questions, answers in [
            (["Жду автобус, пешком идти далеко", "О, как раз подъехал"], ["Давно стоишь?", "О, дождался"]),
            (["Исправил ошибку в проекте", "Да, теперь всё запускается"], ["Проверил запуск?", "О, имба, получилось"]),
            (["Лена одолжила мне ручку, а я Саше тетрадь", "Ей ещё не вернул"], ["Оке", "Ручку Лене?"]),
            (["Хочу сделать омлет", "Только одно осталось"], ["Яйца есть?", "На маленькую порцию хватит"]),
            (["Осталось доделать один слайд", "А что на нём должно быть?"], ["Уже почти закончил", "Ты не говорил, что на него планировал"]),
        ]:
            with self.subTest(questions=questions):
                state = initial_state()
                for question, answer in zip(questions, answers):
                    reply = self.reply(question, state)
                    self.assertEqual(reply["text"], answer)
                    state = apply_reply(state, question, reply)
                self.assertIsNone(self.corpus.match(questions[-1]))

    def test_context_speaker_recency_and_negation_are_required(self):
        question = "Жду автобус, пешком идти далеко"
        state = apply_reply(initial_state(), question, self.reply(question))
        self.assertEqual(self.reply("О, как раз подъехал", state)["text"], "О, дождался")
        wrong = [{"question": "Давно стоишь?", "text": question}]
        self.assertIsNone(self.corpus.match("О, как раз подъехал", wrong))
        self.assertIsNone(self.corpus.match("О, как раз не подъехал", state["history"]))
        state = apply_reply(state, "Совсем другая тема", self.reply("Совсем другая тема"))
        self.assertIsNone(self.corpus.match("О, как раз подъехал", state["history"]))

    def test_format_promises_math_and_persona_remain_excluded(self):
        for question in ("Можешь отвечать покороче?", "Давай без встречных вопросов", "Не используй сокращения",
                         "У нас три команды по четыре человека. Сколько всего участников?",
                         "Тайвань это город Китая", "Даже если чай предлагают?"):
            self.assertIsNone(self.corpus.match(question))
        self.assertIn("чай", self.reply("Чай или кофе?")["text"].lower())
        self.assertEqual(self.reply("Сколько будет 19 умножить на 7?")["text"], "133.")

    def test_quoted_translation_only_for_exact_known_literal(self):
        self.assertEqual(self.reply("Переведи «I forgot my keys»")["text"], "Я забыл ключи")
        self.assertIsNone(self.corpus.match("Переведи «I forgot my passport»"))
        self.assertIsNone(self.corpus.match("Друг говорит: «Не могу найти ключи, хотя точно принёс их домой»"))
        for question in ("Переведи I forgot «my keys»", "Переведи «I forgot my» keys",
                         "Как по-простому перевести Let's «go»?", "Переведи «I forgot my keys"):
            self.assertIsNone(self.corpus.match(question))

    def test_question_is_not_a_confirmed_context_fact(self):
        question = "Надя принесёт настолку? Илья принесёт еду?"
        self.assertIsNone(self.corpus.match(question))
        state = apply_reply(initial_state(), question, self.reply(question))
        self.assertIsNone(self.corpus.match("Кто игру приносит, напомни?", state["history"]))
        self.assertNotEqual(self.reply("Кто игру приносит, напомни?", state)["text"], "Надя")
        quoted_history = [{"question": "«Я сегодня сдал экзамен.»", "text": "Что ты цитируешь?"}]
        self.assertIsNone(self.corpus.match("Вроде нормально", quoted_history))

    def test_task_selection_is_not_travel_advice(self):
        reply = self.reply("У меня три задания на завтра, не знаю за что взяться")
        self.assertEqual(reply["text"], "А какое быстрее всего сделать?")
        self.assertEqual(reply["intent"], "corpus")

    def test_current_activity_is_not_a_general_preference(self):
        reply = self.reply("Что сейчас слушаешь?")
        self.assertEqual(reply["text"], "Сейчас ничего. А что предложишь?")
        self.assertEqual(reply["intent"], "corpus")
        self.assertTrue(self.reply("Ты сейчас слушаешь музыку?")["fallback"])

    def test_all_350_prompts_bounded_offline_and_no_held_source_selected(self):
        with closing(sqlite3.connect(self.path)) as connection:
            records = connection.execute("SELECT id,prompt,approved FROM corpus_replies").fetchall()
        held = {record[0] for record in records if not record[2]}
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")):
            for _, question, _ in records:
                reply = self.reply(question)
                self.assertTrue(reply["text"].strip())
                self.assertLessEqual(len(reply["text"].encode("utf-16-le")) // 2, 300)
                self.assertFalse(set(reply["facts"]) & held)

    def test_ambiguity_checks_all_tied_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous.sqlite3"
            with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(path)) as target:
                source.backup(target)
            with closing(sqlite3.connect(path)) as target:
                candidates = target.execute("SELECT id FROM corpus_replies WHERE approved=1 ORDER BY id LIMIT 3").fetchall()
                for index, (identifier,) in enumerate(candidates):
                    target.execute("UPDATE corpus_replies SET prompt=?,answer=?,context='' WHERE id=?",
                                   ("Проверочная неоднозначная реплика", "Первый ответ" if index < 2 else "Другой ответ", identifier))
                    target.execute("UPDATE corpus_reviews SET context_turns_json='null' WHERE reply_id=?", (identifier,))
                target.commit()
            self.assertIsNone(Corpus(path).match("Проверочная неоднозначная реплика"))

    def test_default_spawn_has_zero_artificial_wait(self):
        runtime = Runtime(self.db, corpus_path=self.path)
        reply = runtime.respond("Не могу найти ключи, хотя точно принёс их домой")
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["target_seconds"], 0)
        self.assertEqual(reply["text"], "В карманах и сумке смотрел?")


if __name__ == "__main__":
    unittest.main()
