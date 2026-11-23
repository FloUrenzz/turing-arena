"""Prepare reviewed dialogue workbooks for offline use, without Excel dependencies."""

import hashlib
import json
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
SOURCE_APPROVAL_POLICY = "Подтверждаю: final answer; Правка: nonempty edit; Проверить/Убрать: inactive"
REVIEW_APPROVAL_POLICY = "review overlay: accept/rewrite active; hold inactive; original source status retained separately"
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
REVIEW_SCHEMA = """
CREATE TABLE corpus_reviews(reply_id TEXT PRIMARY KEY REFERENCES corpus_replies(id),
 decision TEXT NOT NULL CHECK(decision IN ('accept','rewrite','hold')), reason TEXT NOT NULL,
 original_answer TEXT NOT NULL, original_context TEXT NOT NULL, context_turns_json TEXT NOT NULL);
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


def _validate_answer(answer, path, sheet=None, row=None):
    if not isinstance(answer, str) or not answer.strip():
        raise _error(path, "активный ответ должен быть непустым текстом", sheet, row)
    if any(unicodedata.category(c).startswith("C") and not c.isspace() for c in answer):
        raise _error(path, "управляющие символы в ответе", sheet, row)
    if len(answer) > 300 or len(answer.encode("utf-16-le")) // 2 > 300:
        raise _error(path, "активный ответ длиннее 300 символов", sheet, row)
    if any(c.isalpha() for c in answer) and not re.search(r"[А-Яа-яЁё]", answer):
        raise _error(path, "активный ответ должен быть на русском", sheet, row)


def _records(path, checksum, validate_active=True):
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
            if approved and validate_active:
                _validate_answer(answer, path, sheet, number)
            record_id = source_id + ":" + str(number)
            records.append((record_id, source_id, number, data["№"], data["Тема"],
                            data["До этого в разговоре"], data["Что пишут"], answer, status,
                            int(approved), data.get("Источник", ""), data["Примечание"]))
        if not records:
            raise _error(path, "лист не содержит примеров", sheet)
        yield (source_id, path.name, checksum, sheet), records


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("повтор JSON поля " + key)
        result[key] = value
    return result


def _review_text(value, label, path, limit=8000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _error(path, label + " должен быть непустым текстом допустимой длины")
    if any(unicodedata.category(c).startswith("C") and not c.isspace() for c in value):
        raise _error(path, "управляющие символы в " + label)


def _apply_review(review_path, sources, records):
    path = Path(review_path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("слишком большой JSON проверки")
        raw = path.read_bytes()
        review = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_json_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise _error(path, "не удалось прочитать проверку: " + str(exc)) from exc
    root_fields = {"schema_version", "reviewer", "authorization", "sources", "decisions"}
    if not isinstance(review, dict) or set(review) != root_fields:
        raise _error(path, "неверные корневые поля проверки")
    if type(review["schema_version"]) is not int or review["schema_version"] != 1:
        raise _error(path, "неверная schema_version проверки")
    _review_text(review["reviewer"], "reviewer", path)
    if "ai-assisted" not in review["reviewer"].casefold():
        raise _error(path, "reviewer должен явно содержать AI-assisted")
    _review_text(review["authorization"], "authorization", path)
    expected_sources = {}
    for _, filename, checksum, _ in sources:
        if filename in expected_sources and expected_sources[filename] != checksum:
            raise _error(path, "имена источников неоднозначны")
        expected_sources[filename] = checksum
    if not isinstance(review["sources"], dict) or review["sources"] != expected_sources:
        raise _error(path, "sources или SHA256 не совпадают с исходниками")
    if not isinstance(review["decisions"], list):
        raise _error(path, "decisions должен быть списком")
    by_id = {record[3]: record for record in records}
    decisions = {}
    for item in review["decisions"]:
        required = {"example_id", "decision", "reason"}
        allowed = required | {"answer", "context_turns"}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - allowed:
            raise _error(path, "неверные поля решения")
        example_id = item["example_id"]
        if not isinstance(example_id, str) or example_id not in by_id:
            raise _error(path, "неизвестный example_id")
        if example_id in decisions:
            raise _error(path, "повтор example_id " + example_id)
        decision = item["decision"]
        if not isinstance(decision, str) or decision not in {"accept", "rewrite", "hold"}:
            raise _error(path, "неверное решение для example_id " + example_id)
        _review_text(item["reason"], "reason example_id=" + example_id, path)
        if decision != "rewrite" and set(item) != required:
            raise _error(path, "answer/context_turns допустимы только для rewrite")
        if decision == "rewrite":
            if "answer" not in item:
                raise _error(path, "rewrite требует answer для example_id " + example_id)
            _validate_answer(item["answer"], path, row=example_id)
            if "context_turns" in item:
                turns = item["context_turns"]
                if not isinstance(turns, list) or not 1 <= len(turns) <= 4:
                    raise _error(path, "context_turns должен содержать от 1 до 4 реплик")
                for turn in turns:
                    if not isinstance(turn, dict) or set(turn) != {"role", "text"}:
                        raise _error(path, "неверные поля context_turns")
                    if not isinstance(turn["role"], str) or turn["role"] not in {"user", "bot"}:
                        raise _error(path, "неверная role в context_turns")
                    _review_text(turn["text"], "context_turns.text", path, limit=4000)
                    if turn["role"] == "bot":
                        _validate_answer(turn["text"], path, row=example_id)
        decisions[example_id] = item
    if set(decisions) != set(by_id):
        raise _error(path, "пропущены решения example_id: " + ", ".join(sorted(set(by_id) - set(decisions))))
    effective, reviews = [], []
    counts = {"review_accepted": 0, "review_rewritten": 0, "review_held": 0}
    count_names = {"accept": "review_accepted", "rewrite": "review_rewritten", "hold": "review_held"}
    for record in records:
        item = decisions[record[3]]
        decision = item["decision"]
        updated = list(record)
        if decision == "rewrite":
            updated[7] = item["answer"]
        updated[9] = int(decision != "hold")
        if updated[9]:
            _validate_answer(updated[7], path, row=record[3])
        effective.append(tuple(updated))
        reviews.append((record[0], decision, item["reason"], record[7], record[5],
                        json.dumps(item.get("context_turns"), ensure_ascii=False)))
        counts[count_names[decision]] += 1
    source_approved = sum(record[9] for record in records)
    metadata = [("review_schema", "1"), ("reviewer", review["reviewer"]),
                ("authorization", review["authorization"]),
                ("review_sha256", hashlib.sha256(raw).hexdigest()),
                ("source_approved", str(source_approved)),
                ("source_pending", str(len(records) - source_approved))]
    return effective, reviews, metadata, counts


def build_corpus(sources, destination, *, review_path=None):
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
            for source, records in _records(path, checksum, validate_active=review_path is None):
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
    review_rows, review_metadata, review_counts = [], [], {}
    if review_path is not None:
        all_records, review_rows, review_metadata, review_counts = _apply_review(review_path, all_sources, all_records)
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
            if review_path is not None:
                connection.executescript(REVIEW_SCHEMA)
                connection.executemany("INSERT INTO corpus_reviews VALUES(?,?,?,?,?,?)", review_rows)
            connection.executemany("INSERT INTO corpus_metadata VALUES(?,?)", [
                ("schema_version", "1"), ("importer", "arena.corpus_import"),
                ("approval_policy", SOURCE_APPROVAL_POLICY if review_path is None else REVIEW_APPROVAL_POLICY),
            ])
            if review_path is not None:
                connection.execute("INSERT INTO corpus_metadata VALUES(?,?)",
                                   ("source_approval_policy", SOURCE_APPROVAL_POLICY))
            connection.executemany("INSERT INTO corpus_metadata VALUES(?,?)", review_metadata)
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
            "pending": len(all_records) - approved, "sources": len(all_sources), **review_counts}
