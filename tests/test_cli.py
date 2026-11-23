import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CliChecks(unittest.TestCase):
    def invoke(self, *arguments, input=None):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "main.py", *arguments],
            cwd=ROOT, input=input, text=True, encoding="utf8",
            capture_output=True, timeout=8, check=True,
        )

    def test_default_short_and_long_json_have_no_artificial_wait(self):
        questions = ["Привет", "Почему после дождя иногда появляется радуга? Объясни простыми словами."]
        lengths = []
        for question in questions:
            with self.subTest(question=question):
                result = self.invoke("--ask", question, "--json", "--no-corpus")
                reply = json.loads(result.stdout)
                self.assertEqual(reply["status"], "ok")
                self.assertEqual(reply["target_seconds"], 0)
                self.assertLess(reply["elapsed"], 3)
                self.assertTrue(reply["text"].strip())
                self.assertLessEqual(len(reply["text"].encode("utf-16-le")) // 2, 300)
                lengths.append(len(reply["text"]))
        self.assertGreater(lengths[1], lengths[0])

    def test_plain_output_and_legacy_fast_are_identical(self):
        args = ("--ask", "Сколько будет 19 умножить на 7?", "--no-corpus")
        default = self.invoke(*args)
        legacy = self.invoke(*args, "--fast")
        self.assertEqual(default.stdout, "133.\n")
        self.assertEqual(legacy.stdout, default.stdout)
        self.assertNotIn("Исследовательский режим", default.stderr + legacy.stderr)
        self.assertIn("Время до выдачи:", default.stderr)

    def test_default_chat_immediately_delivers_each_question(self):
        result = self.invoke("--chat", "--json", "--no-corpus", input=(
            "Сколько будет 19 умножить на 7?\n"
            "Почему после дождя иногда появляется радуга? Объясни простыми словами.\n"
        ))
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0]["text"], "133.")
        self.assertTrue(all(reply["target_seconds"] == 0 and reply["status"] == "ok" for reply in replies))
        self.assertTrue(all(reply["elapsed"] < 3 for reply in replies))


if __name__ == "__main__":
    unittest.main()
