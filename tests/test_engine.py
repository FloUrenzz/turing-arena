from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from arena.data import ensure_demo_database
from arena.engine import calculate, generate
from arena.models import apply_reply, initial_state


class EngineChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = ensure_demo_database()

    def setUp(self):
        self.state = initial_state()

    def reply(self, question):
        result = generate(question, self.state, self.db)
        self.assertTrue(result["text"].strip())
        self.assertLessEqual(len(result["text"]), 300)
        self.state = apply_reply(self.state, question, result)
        return result

    def test_exact_organizer_questions(self):
        questions = [
            ("Почему после дождя иногда появляется радуга? Объясни простыми словами.", "explanation", "rainbow_cause"),
            ("Что бы ты посоветовал человеку, который впервые приехал в Астану зимой?", "advice", "astana_winter"),
            ("Друг опоздал на встречу на полчаса и извинился. Что бы ты ему ответил?", "social", "late_apology"),
        ]
        for question, intent, fact in questions:
            with self.subTest(question=question):
                result = self.reply(question)
                self.assertEqual(result["intent"], intent)
                self.assertIn(fact, result["facts"])
                self.assertFalse(result["fallback"])

    def test_rainbow_variants_and_followup(self):
        for question in ("Как возникает радуга?", "Из-за чего мы видим радугу после ливня?",
                         "Откуда берутся разноцветные полосы радуги?"):
            self.assertEqual(self.reply(question)["intent"], "explanation")
        self.assertIn("rainbow_conditions", self.reply("А без солнца?")["facts"])
        self.assertTrue(self.reply("Почему твой друг любит радугу?")["fallback"])

    def test_winter_summer_and_negation(self):
        for question in ("Еду в Астану зимой. Что взять?", "Как одеться для первой зимней поездки в Астану?",
                         "Посоветуй что-нибудь новичку: Астана, мороз."):
            self.assertIn("astana_winter", self.reply(question)["facts"])
        for question in ("Что посоветуешь для поездки в Астану летом?",
                         "Еду в Астану не зимой, а летом. Что взять?"):
            reply = self.reply(question)
            self.assertIn("summer_city", reply["facts"])
            self.assertNotIn("перчатки", reply["text"])

    def test_social_roles_and_apology_negation(self):
        examples = [("Друг задержался и попросил прощения. Что сказать?", "late_apology"),
                    ("Друг опоздал и даже не извинился. Как реагировать?", "late_no_apology"),
                    ("Я опоздал на встречу. Что написать другу?", "self_late")]
        for question, topic in examples:
            with self.subTest(question=question):
                self.assertEqual(self.reply(question)["topic"], topic)
        self.assertNotEqual(self.reply("Друг не опоздал на встречу. Что ответить?")["intent"], "social")

    def test_persona_consistency_and_new_word_forms(self):
        positive = self.reply("Почему ты не любишь чай?")
        self.assertIn("Я люблю чай", positive["text"])
        negative = self.reply("Почему ты любишь кофе?")
        self.assertIn("не очень люблю кофе", negative["text"])
        self.assertIn("likes_programming", self.reply("Как относишься к программированию?")["facts"])
        self.assertIn("likes_tea", self.reply("Между кофе и чаем что предпочитаешь?")["facts"])

    def test_unknown_and_third_party_not_invented(self):
        for question in ("Что такое флюмп?", "Тебе нравится кофе или бжумп?",
                         "Почему твой сосед любит музыку?", "Какой курс валют прямо сейчас?",
                         "Что выберешь: гравитон или ксиломорф?"):
            with self.subTest(question=question):
                self.assertTrue(self.reply(question)["fallback"])

    def test_memory_only_after_commit_and_subject_attribution(self):
        old = deepcopy(self.state)
        pending = generate("Меня зовут Дина.", self.state, self.db)
        self.assertEqual(old, self.state)
        self.assertTrue(generate("Как меня зовут?", self.state, self.db)["fallback"])
        self.state = apply_reply(self.state, "Меня зовут Дина.", pending)
        self.assertIn("Дина", self.reply("Как меня зовут?")["text"])
        self.reply("Я люблю кофе.")
        self.assertIn("кофе", self.reply("Что я люблю?")["text"])
        self.assertIn("likes_tea", self.reply("А ты что предпочитаешь?")["facts"])

    def test_quoted_identity_not_recorded(self):
        self.reply('Друг сказал: «Меня зовут Олег».')
        self.assertTrue(self.reply("Как меня зовут?")["fallback"])

    def test_new_topic_clears_old_reference(self):
        self.reply("Почему появляется радуга?")
        self.reply("Как тебя зовут?")
        self.assertNotIn("rainbow_cause", self.reply("А почему?")["facts"])

    def test_safe_operations_generalize(self):
        self.assertEqual(calculate("(18 + 7) * 4"), "100")
        self.assertEqual(calculate("0.1 + 0.2"), "0.3")
        self.assertEqual(calculate("-7//3"), "-3")
        self.assertEqual(calculate("-7%3"), "2")
        for text in ("2**100000000", "__import__('os')", "1/0"):
            with self.assertRaises(Exception):
                calculate(text)
        self.assertEqual(self.reply("Переверни слово «самолёт».")["text"], "тёломас")
        self.assertEqual(self.reply("Сколько будет 13 умножить на 7?")["text"], "91")
        self.assertEqual(self.reply("Назови последнюю букву слова «арбуз».")["text"], "з")

    def test_engine_works_with_socket_calls_forbidden(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")):
            self.assertFalse(self.reply("Почему появляется радуга?")["fallback"])

    def test_replacing_facts_changes_replies(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "different.sqlite3"
            source = sqlite3.connect(self.db)
            target = sqlite3.connect(destination)
            source.backup(target)
            target.execute("UPDATE facts SET object='Лера' WHERE predicate='name'")
            target.execute("UPDATE facts SET value=-3 WHERE object='tea'")
            target.execute("UPDATE facts SET value=3 WHERE object='coffee'")
            target.commit()
            source.close()
            target.close()
            self.assertEqual(generate("Как тебя зовут?", self.state, destination)["text"], "Лера")
            self.assertIn("coffee", generate("Чай или кофе?", self.state, destination)["concepts"])
            self.assertIn("likes_coffee", generate("Чай или кофе?", self.state, destination)["facts"])

    def test_long_and_control_characters_bounded(self):
        for question in ("я" * 50000, "\x1b[31m", "", "\n", "😀" * 5000):
            self.reply(question)

    def test_event_negation_and_contrast(self):
        self.assertEqual(self.reply("Друг не выиграл олимпиаду. Что ему написать?")["topic"], "setback")
        self.assertEqual(self.reply("Подруга не провалила экзамен, а сдала его. Как её поддержать?")["topic"], "success")
        self.assertNotEqual(self.reply("Друг не забыл поздравить меня. Что сказать?")["topic"], "forgotten_birthday")

    def test_reverse_season_contrast(self):
        reply = self.reply("Посоветуй одежду: в Астану еду не летом, а зимой.")
        self.assertIn("astana_winter", reply["facts"])
        self.assertNotIn("в жару", reply["text"])

    def test_name_and_preference_corrections(self):
        self.reply("Меня зовут Лада.")
        self.reply("Меня зовут не Лада, а Вера.")
        self.assertIn("Вера", self.reply("Как меня зовут?")["text"])
        self.reply("Я люблю кофе.")
        self.reply("Я люблю не кофе, а чай.")
        result = self.reply("Что я люблю?")
        self.assertIn("чай", result["text"])
        self.assertNotIn("кофе", result["text"])
        self.reply("Это мой друг сказал: я люблю кофе.")
        self.assertIn("чай", self.reply("Что я люблю?")["text"])

    def test_unknown_relation_not_replaced_by_known_noun(self):
        for question in ("Почему радуга пахнет мятой?", "Почему радуга влияет на курс тенге?",
                         "Почему радуга называется радугой?", "Что посоветуешь против зимней депрессии?",
                         "Тебе нравится чай с квазибрумом?", "Объясни, почему я люблю чай."):
            with self.subTest(question=question):
                result = self.reply(question)
                self.assertTrue(result["fallback"])
                self.assertFalse(result["updates"])

    def test_inverse_role_and_elliptical_followups(self):
        result = self.reply("На встречу опоздал я, а друг извинился за резкость. Что ему ответить?")
        self.assertIn("self_late", result["facts"])
        self.assertNotIn("напиши заранее", result["text"])
        self.reply("Любишь программирование?")
        self.assertIn("likes_music", self.reply("А музыку?")["facts"])
        self.assertEqual(self.reply("Почему?")["intent"], "reason")

    def test_absence_and_universal_claim_have_conditions(self):
        self.assertIn("rainbow_conditions", self.reply("Почему радуга не появилась, хотя дождь прошёл?")["facts"])
        self.assertIn("rainbow_conditions", self.reply("Радуга появляется после любого дождя? Объясни.")["facts"])

    def test_new_fact_does_not_license_unrelated_cause(self):
        self.assertTrue(self.reply("Почему после дождя исчезает интернет?")["fallback"])
        self.assertTrue(self.reply("Почему радуга появилась на логотипе компании?")["fallback"])
        self.assertFalse(self.reply("Почему появляется радуга на небе?")["fallback"])
        self.assertIn("likes_rain", self.reply("Почему ты любишь дождь?")["facts"])

    def test_relation_paraphrases_and_explicit_month(self):
        self.assertIn("rainbow_cause", self.reply("Отчего после ливня в небе бывает цветная дуга?")["facts"])
        self.assertIn("rainbow_cause", self.reply("Как связаны капли воды и появление радуги?")["facts"])
        self.assertIn("astana_winter", self.reply("Впервые лечу в Астану в январе. Что надеть?")["facts"])
        self.assertEqual(self.reply("Приятель пришёл с опозданием и сказал: прости. Что ему ответить?")["topic"], "late_apology")
        self.assertEqual(self.reply("Друг задержался, но прощения не попросил. Как реагировать?")["topic"], "late_no_apology")


if __name__ == "__main__":
    unittest.main()
