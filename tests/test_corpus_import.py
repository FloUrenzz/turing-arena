import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from arena.corpus_import import build_corpus


ROOT = Path(__file__).resolve().parent.parent
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
HEADERS = ["№", "Тема", "До этого в разговоре", "Что пишут", "Ответ бота", "Решение", "Твоя правка", "Примечание"]


def workbook(path, records, headers=None, formula=None, external=False):
    headers = headers or HEADERS
    worksheet = ET.Element("worksheet", xmlns=NS)
    sheet_data = ET.SubElement(worksheet, "sheetData")
    for number, record in enumerate([headers] + records, 6):
        row = ET.SubElement(sheet_data, "row", r=str(number))
        for offset, value in enumerate(record):
            cell = ET.SubElement(row, "c", r=chr(65 + offset) + str(number), t="inlineStr")
            if formula == (number, offset):
                ET.SubElement(cell, "f").text = '"cached"'
                ET.SubElement(cell, "v").text = "Привет"
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = str(value)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", ET.tostring(worksheet))
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Реплики" sheetId="1" r:id="r1"/></sheets></workbook>')
        mode = ' TargetMode="External"' if external else ""
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"{mode}/></Relationships>')


def row(identifier=1, status="Подтверждаю", answer="Привет", edit=""):
    return [str(identifier), "Разговор", "", "Привет, как ты?", answer, status, edit, ""]


def review_document(source, decisions):
    return {"schema_version": 1, "reviewer": "AI-assisted test review",
            "authorization": "Пользователь разрешил проверить и подключить",
            "sources": {source.name: hashlib.sha256(source.read_bytes()).hexdigest()},
            "decisions": decisions}


def decision(identifier=1, choice="accept", **extra):
    return {"example_id": str(identifier), "decision": choice, "reason": "Проверено в тесте", **extra}


def save_review(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class CorpusImportTests(unittest.TestCase):
    def test_statuses_final_text_provenance_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.xlsx", Path(directory) / "corpus.sqlite3"
            workbook(source, [row(1, edit="Старая правка"), row(2, "Правка", edit="Новая правка"),
                              row(3, "Проверить"), row(4, "Убрать")])
            checksum = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(build_corpus([source], output), {"rows": 4, "approved": 2, "pending": 2, "sources": 1})
            with closing(sqlite3.connect(output)) as connection:
                self.assertEqual(connection.execute("SELECT answer,approved FROM corpus_replies ORDER BY example_id").fetchall(),
                                 [("Привет", 1), ("Новая правка", 1), ("Привет", 0), ("Привет", 0)])
                self.assertEqual(connection.execute("SELECT filename,sha256,sheet FROM corpus_sources").fetchone(),
                                 (source.name, checksum, "Реплики"))
            before = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "существует"):
                build_corpus([source], output)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), checksum)

    def test_reordered_columns_read_by_header(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.xlsx", Path(directory) / "corpus.sqlite3"
            workbook(source, [list(reversed(row()))], headers=list(reversed(HEADERS)))
            self.assertEqual(build_corpus([source], output)["approved"], 1)
            with closing(sqlite3.connect(output)) as c:
                self.assertEqual(c.execute("SELECT prompt, answer FROM corpus_replies").fetchone(), ("Привет, как ты?", "Привет"))

    def test_validation_failure_leaves_no_database(self):
        cases = [([row(status="Неизвестно")], None, "статус"),
                 ([row(status="Правка")], None, "итоговый текст"),
                 ([row(answer="я" * 301)], None, "300"),
                 ([row(answer="a" * 4)], None, "русском"),
                 ([row(answer="я" + "😀" * 150)], None, "300"),
                 ([row(), row()], None, "повтор номера"),
                 ([row()], (7, 4), "формула")]
        for records, formula, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                source, output = Path(directory) / "source.xlsx", Path(directory) / "corpus.sqlite3"
                workbook(source, records, formula=formula)
                with self.assertRaisesRegex(ValueError, expected):
                    build_corpus([source], output)
                self.assertFalse(output.exists())

    def test_duplicate_header_and_external_relationship_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.xlsx", Path(directory) / "corpus.sqlite3"
            workbook(source, [row() + ["Лишний ответ"]], headers=HEADERS + ["Ответ бота"])
            with self.assertRaisesRegex(ValueError, "повтор заголовка"):
                build_corpus([source], output)
            workbook(source, [row()], external=True)
            with self.assertRaisesRegex(ValueError, "внешние"):
                build_corpus([source], output)

    def test_untrusted_archive_paths_and_dtd_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.xlsx", Path(directory) / "corpus.sqlite3"
            workbook(source, [row()])
            with zipfile.ZipFile(source, "a") as z:
                z.writestr("../outside.xml", "irrelevant")
            with self.assertRaisesRegex(ValueError, "небезопасный путь"):
                build_corpus([source], output)
            with zipfile.ZipFile(source, "w") as z:
                z.writestr("xl/sharedStrings.xml", '<!DOCTYPE x [<!ENTITY x "bad">]><x/>')
            with self.assertRaisesRegex(ValueError, "DTD"):
                build_corpus([source], output)
            self.assertFalse(output.exists())

    def test_cli_prepares_actual_workbooks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "corpus.sqlite3"
            command = [sys.executable, "-X", "utf8", str(ROOT / "scripts/import_corpus.py"),
                       str(ROOT / "datasets"), "--output", str(output)]
            result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"rows": 350, "approved": 150, "pending": 200, "sources": 2})
            again = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=10)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("существует", again.stderr)

    def test_actual_workbooks_all_statuses_and_checksums(self):
        sources = sorted((ROOT / "datasets").glob("*.xlsx"))
        self.assertEqual(len(sources), 2)
        checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "corpus.sqlite3"
            self.assertEqual(build_corpus(sources, output), {"rows": 350, "approved": 150, "pending": 200, "sources": 2})
            with closing(sqlite3.connect(output)) as c:
                self.assertEqual(dict(c.execute("SELECT filename,sha256 FROM corpus_sources")), checksums)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM corpus_replies WHERE CAST(example_id AS INT)>150 AND approved=1").fetchone()[0], 0)
                self.assertEqual(c.execute("SELECT answer FROM corpus_replies WHERE example_id='106'").fetchone()[0], "а чо случилось?")
            self.assertEqual(checksums, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})

    def test_review_activates_pending_rewrites_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, review = (Path(directory) / name for name in ("source.xlsx", "corpus.sqlite3", "review.json"))
            records = [row(1, "Проверить", answer="Старый ответ"), row(2, "Подтверждаю", answer="Исходный ответ"),
                       row(3, "Проверить", answer="Не подключать")]
            records[1][2] = "Исходный контекст"
            workbook(source, records)
            source_bytes = source.read_bytes()
            turns = [{"role": "bot", "text": "Моя реплика"}, {"role": "user", "text": "Слова человека"}]
            save_review(review, review_document(source, [decision(3, "hold"), decision(1),
                        decision(2, "rewrite", answer="Новый ответ", context_turns=turns)]))
            counts = build_corpus([source], output, review_path=review)
            self.assertEqual(counts, {"rows": 3, "approved": 2, "pending": 1, "sources": 1,
                                      "review_accepted": 1, "review_rewritten": 1, "review_held": 1})
            with closing(sqlite3.connect(output)) as c:
                self.assertEqual(c.execute("SELECT example_id,answer,status,approved FROM corpus_replies ORDER BY example_id").fetchall(),
                                 [("1", "Старый ответ", "Проверить", 1), ("2", "Новый ответ", "Подтверждаю", 1),
                                  ("3", "Не подключать", "Проверить", 0)])
                original, context, stored_turns = c.execute("SELECT original_answer,original_context,context_turns_json FROM corpus_reviews JOIN corpus_replies ON reply_id=corpus_replies.id WHERE example_id='2'").fetchone()
                self.assertEqual((original, context), ("Исходный ответ", "Исходный контекст"))
                self.assertEqual(json.loads(stored_turns), turns)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM corpus_reviews").fetchone()[0], 3)
                self.assertEqual(c.execute("SELECT context_turns_json FROM corpus_reviews JOIN corpus_replies ON reply_id=corpus_replies.id WHERE example_id='1'").fetchone()[0], "null")
                metadata = dict(c.execute("SELECT key,value FROM corpus_metadata"))
                self.assertEqual((metadata["review_schema"], metadata["source_approved"], metadata["source_pending"]), ("1", "1", "2"))
                self.assertEqual(metadata["review_sha256"], hashlib.sha256(review.read_bytes()).hexdigest())
                self.assertEqual(metadata["reviewer"], "AI-assisted test review")
                self.assertIn("review overlay", metadata["approval_policy"])
                self.assertIn("accept/rewrite active", metadata["approval_policy"])
                self.assertIn("Проверить/Убрать: inactive", metadata["source_approval_policy"])
            self.assertEqual(source.read_bytes(), source_bytes)
            output_bytes = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "существует"):
                build_corpus([source], output, review_path=review)
            self.assertEqual(output.read_bytes(), output_bytes)

    def test_review_validates_effective_active_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, review = (Path(directory) / name for name in ("source.xlsx", "corpus.sqlite3", "review.json"))
            workbook(source, [row(answer="я" * 301)])
            save_review(review, review_document(source, [decision(1, "rewrite", answer="Исправленный ответ")]))
            self.assertEqual(build_corpus([source], output, review_path=review)["approved"], 1)

    def test_review_rejects_missing_unknown_duplicate_ids_and_invalid_metadata(self):
        def altered(kind, source):
            data = review_document(source, [decision()])
            if kind == "missing":
                data["decisions"] = []
            elif kind == "unknown":
                data["decisions"] = [decision(2)]
            elif kind == "duplicate":
                data["decisions"] *= 2
            elif kind == "sha":
                data["sources"][source.name] = "0" * 64
            elif kind == "extra_source":
                data["sources"]["extra.xlsx"] = "0" * 64
            elif kind == "missing_source":
                data["sources"] = {}
            elif kind == "root_key":
                data["extra"] = 1
            elif kind == "schema_bool":
                data["schema_version"] = True
            elif kind == "reviewer_label":
                data["reviewer"] = "Team confirmed"
            elif kind == "authorization_type":
                data["authorization"] = False
            elif kind == "id_type":
                data["decisions"][0]["example_id"] = 1
            elif kind == "decisions_type":
                data["decisions"] = {}
            return data
        for kind in ("missing", "unknown", "duplicate", "sha", "extra_source", "missing_source", "root_key",
                     "schema_bool", "reviewer_label", "authorization_type", "id_type", "decisions_type"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                source, output, review = (Path(directory) / name for name in ("source.xlsx", "corpus.sqlite3", "review.json"))
                workbook(source, [row()])
                save_review(review, altered(kind, source))
                with self.assertRaises(ValueError):
                    build_corpus([source], output, review_path=review)
                self.assertFalse(output.exists())

    def test_review_strict_decision_answer_and_context_types(self):
        invalid = [decision(choice="unknown"), decision(reason=""), decision(extra="unexpected"),
                   decision(answer="Не разрешено"), decision(context_turns=[]),
                   decision(choice="hold", answer="Не разрешено"),
                   decision(choice="rewrite"), decision(choice="rewrite", answer=5),
                   decision(choice="rewrite", answer="я" * 301),
                   decision(choice="rewrite", answer="я" + "😀" * 150),
                   decision(choice="rewrite", answer="hello"),
                   decision(choice="rewrite", answer="Привет\x00"),
                   decision(choice="rewrite", answer="Привет", context_turns=[]),
                   decision(choice="rewrite", answer="Привет", context_turns={}),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "other", "text": "Привет"}]),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "user", "text": "я" * 4001}]),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "user", "text": 1}]),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "user", "text": ""}]),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "bot", "text": "Hello"}]),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "bot", "text": "я" * 301}]),
                   decision(choice="rewrite", answer="Привет", context_turns=[{"role": "user", "text": "Привет", "extra": 0}])]
        for item in invalid:
            with self.subTest(item=item), tempfile.TemporaryDirectory() as directory:
                source, output, review = (Path(directory) / name for name in ("source.xlsx", "corpus.sqlite3", "review.json"))
                workbook(source, [row()])
                save_review(review, review_document(source, [item]))
                with self.assertRaises(ValueError):
                    build_corpus([source], output, review_path=review)
                self.assertFalse(output.exists())

    def test_review_cli_and_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, review = (Path(directory) / name for name in ("source.xlsx", "corpus.sqlite3", "review.json"))
            workbook(source, [row(status="Проверить")])
            save_review(review, review_document(source, [decision()]))
            command = [sys.executable, "-X", "utf8", str(ROOT / "scripts/import_corpus.py"), str(source),
                       "--output", str(output), "--review", str(review)]
            result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["review_accepted"], 1)
            review.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "повтор JSON"):
                build_corpus([source], Path(directory) / "other.sqlite3", review_path=review)


if __name__ == "__main__":
    unittest.main()
