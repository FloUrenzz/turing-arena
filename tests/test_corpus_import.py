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


if __name__ == "__main__":
    unittest.main()
