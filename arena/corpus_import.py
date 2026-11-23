"""Prepare reviewed dialogue workbooks for offline use, without Excel dependencies."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile


NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEADERS = ("№", "Тема", "До этого в разговоре", "Что пишут", "Ответ бота",
           "Решение", "Твоя правка", "Примечание")
STATUSES = {"Подтверждаю", "Правка", "Проверить", "Убрать"}
MAX_BYTES = 32 * 1024 * 1024
SCHEMA = """
CREATE TABLE corpus_sources(id TEXT PRIMARY KEY, filename TEXT NOT NULL,
 sha256 TEXT NOT NULL, sheet TEXT NOT NULL);
CREATE TABLE corpus_replies(id TEXT PRIMARY KEY, source_id TEXT NOT NULL
 REFERENCES corpus_sources(id), row_number INTEGER NOT NULL, example_id TEXT NOT NULL UNIQUE,
 topic TEXT NOT NULL, context TEXT NOT NULL, prompt TEXT NOT NULL, answer TEXT NOT NULL,
 status TEXT NOT NULL, approved INTEGER NOT NULL CHECK(approved IN (0,1)),
 origin TEXT NOT NULL, note TEXT NOT NULL);
CREATE TABLE corpus_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX corpus_approved ON corpus_replies(approved);
"""


def _error(path, message, sheet=None, row=None):
    location = str(path) + (f" / {sheet}" if sheet else "")
    if row is not None:
        location += f" / строка {row}"
    return ValueError(location + ": " + message)


def _xml(archive, name):
    raw = archive.read(name)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD и XML entities запрещены")
    return ET.fromstring(raw)


def _read_workbook(path):
    """Return sheet name / row number / column-value records; never execute formulas."""
    if path.stat().st_size > MAX_BYTES:
        raise _error(path, "слишком большой XLSX")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(i.file_size for i in entries) > MAX_BYTES:
            raise _error(path, "слишком большой распакованный XLSX")
        names = [i.filename for i in entries]
        if len(set(names)) != len(names):
            raise _error(path, "повтор имени ZIP entry")
        for name in names:
            if "\\" in name or name.startswith("/") or ".." in PurePosixPath(name).parts:
                raise _error(path, "небезопасный путь в XLSX")
        shared = []
        if "xl/sharedStrings.xml" in names:
            for item in _xml(archive, "xl/sharedStrings.xml"):
                shared.append("".join(node.text or "" for node in item.findall(".//s:t", NS)))
        rels = {}
        for rel in _xml(archive, "xl/_rels/workbook.xml.rels"):
            if rel.get("TargetMode") == "External":
                raise _error(path, "внешние workbook relationships запрещены")
            target = rel.get("Target", "")
            if "\\" in target or ":" in target or ".." in PurePosixPath(target).parts:
                raise _error(path, "небезопасная workbook relationship")
            name = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rid = rel.get("Id")
            if rid in rels:
                raise _error(path, "повтор relationship Id")
            rels[rid] = name
        sheets = _xml(archive, "xl/workbook.xml").findall("s:sheets/s:sheet", NS)
        if not sheets:
            raise _error(path, "нет листов")
        seen_sheets = set()
        for sheet in sheets:
            title = sheet.get("name", "")
            if not title or title in seen_sheets:
                raise _error(path, "пустое или повторное имя листа")
            seen_sheets.add(title)
            target = rels.get(sheet.get("{" + REL_NS + "}id"))
            if target not in names or not target.startswith("xl/worksheets/"):
                raise _error(path, "отсутствует worksheet", title)
            rows = []
            seen_rows = set()
            for row in _xml(archive, target).findall("s:sheetData/s:row", NS):
                number = int(row.get("r", "0"))
                if number < 1 or number > 100000 or number in seen_rows:
                    raise _error(path, "неверный или повторный номер строки", title, number)
                seen_rows.add(number)
                cells, formulas = {}, set()
                for cell in row.findall("s:c", NS):
                    reference = cell.get("r", "")
                    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", reference)
                    if not match or int(match[2]) != number or match[1] in cells:
                        raise _error(path, "неверная или повторная ячейка", title, number)
                    column = match[1]
                    if cell.find("s:f", NS) is not None:
                        formulas.add(column)
                    value = cell.find("s:v", NS)
                    if cell.get("t") == "inlineStr":
                        text = "".join(t.text or "" for t in cell.findall("s:is//s:t", NS))
                    elif cell.get("t") == "s":
                        if value is None or value.text is None:
                            raise _error(path, "пустой индекс shared string", title, number)
                        index = int(value.text)
                        if not 0 <= index < len(shared):
                            raise _error(path, "неверный индекс shared string", title, number)
                        text = shared[index]
                    else:
                        text = value.text or "" if value is not None else ""
                    cells[column] = text.strip()
                if any(cells.values()) or formulas:
                    rows.append((number, cells, formulas))
            yield title, rows


def _records(path, checksum):
    for sheet, rows in _read_workbook(path):
        header_rows = [(n, cells, formulas) for n, cells, formulas in rows
                       if set(HEADERS).issubset(set(cells.values()))]
        if len(header_rows) != 1:
            raise _error(path, "нужна одна строка со всеми заголовками", sheet)
        header_number, cells, formulas = header_rows[0]
        if formulas:
            raise _error(path, "формула в заголовке", sheet, header_number)
        columns = {}
        for column, label in cells.items():
            if label in (*HEADERS, "Источник"):
                if label in columns:
                    raise _error(path, "повтор заголовка " + label, sheet, header_number)
                columns[label] = column
        source_id = hashlib.sha256((checksum + "\0" + sheet).encode("utf-8")).hexdigest()
        records = []
        for number, values, formulas in rows:
            if number <= header_number:
                continue
            if formulas.intersection(columns.values()):
                raise _error(path, "формула вместо данных", sheet, number)
            data = {label: values.get(column, "") for label, column in columns.items()}
            if not any(data.values()):
                continue
            if any(not data.get(label) for label in ("№", "Тема", "Что пишут", "Ответ бота", "Решение")):
                raise _error(path, "неполная пара реплика–ответ", sheet, number)
            if not re.fullmatch(r"[1-9][0-9]*", data["№"]):
                raise _error(path, "неверный номер примера", sheet, number)
            status = data["Решение"]
            if status not in STATUSES:
                raise _error(path, "неизвестный статус " + status, sheet, number)
            if status == "Правка" and not data["Твоя правка"]:
                raise _error(path, "для Правка нужен итоговый текст", sheet, number)
            # Confirmed workbooks already contain final E; H is historical, not a live override.
            answer = data["Твоя правка"] if status == "Правка" else data["Ответ бота"]
            approved = status in ("Подтверждаю", "Правка")
            if any(len(value) > 8000 for value in data.values()):
                raise _error(path, "слишком длинное поле", sheet, number)
            if approved:
                if len(answer) > 300 or len(answer.encode("utf-16-le")) // 2 > 300:
                    raise _error(path, "активный ответ длиннее 300 символов", sheet, number)
                if any(unicodedata.category(c).startswith("C") and not c.isspace() for c in answer):
                    raise _error(path, "управляющие символы в ответе", sheet, number)
                if any(c.isalpha() for c in answer) and not re.search(r"[А-Яа-яЁё]", answer):
                    raise _error(path, "активный ответ должен быть на русском", sheet, number)
            record_id = source_id + ":" + str(number)
            records.append((record_id, source_id, number, data["№"], data["Тема"],
                            data["До этого в разговоре"], data["Что пишут"], answer, status,
                            int(approved), data.get("Источник", ""), data["Примечание"]))
        if not records:
            raise _error(path, "лист не содержит примеров", sheet)
        yield (source_id, path.name, checksum, sheet), records


def build_corpus(sources, destination):
    """Import XLSX paths into a new SQLite; return row/status/source counts.

    Existing destination files are never replaced. All approved and pending rows
    remain traceable to an unchanged original workbook, sheet and source row.
    """
    destination = Path(destination)
    if destination.exists():
        raise _error(destination, "база уже существует; перезапись запрещена")
    if isinstance(sources, (str, Path)):
        sources = [sources]
    source_paths = sorted((Path(source) for source in sources), key=lambda p: str(p))
    if not source_paths:
        raise ValueError("Не указаны XLSX источники")
    all_sources, all_records, seen_examples, seen_checksums = [], [], set(), set()
    for path in source_paths:
        try:
            if path.suffix.lower() != ".xlsx":
                raise _error(path, "ожидается XLSX")
            if path.stat().st_size > MAX_BYTES:
                raise _error(path, "слишком большой XLSX")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum in seen_checksums:
                raise _error(path, "повтор одного исходного файла")
            seen_checksums.add(checksum)
            for source, records in _records(path, checksum):
                all_sources.append(source)
                for record in records:
                    if record[3] in seen_examples:
                        raise _error(path, "повтор номера примера " + record[3], source[3], record[2])
                    seen_examples.add(record[3])
                    all_records.append(record)
        except (OSError, KeyError, IndexError, ET.ParseError, zipfile.BadZipFile,
                UnicodeError, RuntimeError) as exc:
            raise _error(path, "не удалось прочитать XLSX: " + str(exc)) from exc
        except ValueError as exc:
            if str(path) in str(exc):
                raise
            raise _error(path, str(exc)) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(SCHEMA)
            connection.executemany("INSERT INTO corpus_sources VALUES(?,?,?,?)", all_sources)
            connection.executemany("INSERT INTO corpus_replies VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", all_records)
            connection.executemany("INSERT INTO corpus_metadata VALUES(?,?)", [
                ("schema_version", "1"), ("importer", "arena.corpus_import"),
                ("approval_policy", "Подтверждаю: final answer; Правка: nonempty edit; Проверить/Убрать: inactive"),
            ])
            connection.commit()
        finally:
            connection.close()
        if os.name == "nt":
            os.rename(temporary, destination)  # Windows rename fails if destination exists.
        else:
            os.link(temporary, destination)  # Atomic no-replace publication on POSIX.
    except OSError as exc:
        raise _error(destination, "не удалось создать новую БД: " + str(exc)) from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    approved = sum(record[9] for record in all_records)
    return {"rows": len(all_records), "approved": approved,
            "pending": len(all_records) - approved, "sources": len(all_sources)}
