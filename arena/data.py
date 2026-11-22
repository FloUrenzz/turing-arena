import json
import math
import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = '''
CREATE TABLE concepts(id TEXT PRIMARY KEY, lemma TEXT NOT NULL, acc TEXT NOT NULL, gender TEXT, definition TEXT);
CREATE TABLE forms(form TEXT NOT NULL, concept TEXT NOT NULL, pos TEXT, features TEXT, PRIMARY KEY(form,concept));
CREATE TABLE facts(id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL, value REAL, reason TEXT);
CREATE TABLE groups(concept TEXT NOT NULL, category TEXT NOT NULL, PRIMARY KEY(concept,category));
CREATE TABLE knowledge(id TEXT PRIMARY KEY, kind TEXT NOT NULL, topic TEXT NOT NULL, attributes_json TEXT NOT NULL, clauses_json TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_seed(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not _text(data.get('provenance')):
        raise ValueError('Неверная версия или происхождение данных')
    ids = set()
    for key in ('concepts', 'facts', 'knowledge'):
        if not isinstance(data.get(key), list):
            raise ValueError('Отсутствует список ' + key)
    for entry in data['concepts']:
        if not isinstance(entry, dict) or any(not _text(entry.get(k)) for k in ('id','lemma','acc')):
            raise ValueError('Неверная запись понятия')
        if entry['id'] in ids:
            raise ValueError('Повтор идентификатора понятия')
        ids.add(entry['id'])
        if not isinstance(entry.get('forms'), list) or not entry['forms'] or not all(_text(x) for x in entry['forms']):
            raise ValueError('Неверные словоформы')
        if not isinstance(entry.get('categories'), list) or not all(_text(x) for x in entry['categories']):
            raise ValueError('Неверные категории')
    for key in ('facts','knowledge'):
        seen = set()
        for entry in data[key]:
            if not isinstance(entry, dict) or not _text(entry.get('id')) or entry['id'] in seen:
                raise ValueError('Неверный или повторный идентификатор ' + key)
            seen.add(entry['id'])
            if key == 'facts':
                if any(not _text(entry.get(k)) for k in ('subject','predicate','object')):
                    raise ValueError('Неверный факт')
                number = entry.get('value')
                if type(number) not in (int,float) or not math.isfinite(number):
                    raise ValueError('Неверная оценка предпочтения')
                if entry['predicate'] == 'likes' and entry['object'] not in ids:
                    raise ValueError('Факт ссылается на неизвестное понятие')
            else:
                if entry.get('kind') not in ('explanation','advice','social') or not _text(entry.get('topic')) or not _text(entry.get('source')):
                    raise ValueError('Неверная запись знания')
                if not isinstance(entry.get('attributes'), dict) or not isinstance(entry.get('clauses'), list):
                    raise ValueError('Неверные атрибуты или смысловые части')
                if not 2 <= len(entry['clauses']) <= 4 or not all(_text(c) and len(c) <= 150 for c in entry['clauses']):
                    raise ValueError('Недопустимая длина смысловых частей')


def build_database(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('База уже существует; автоматическая перезапись запрещена')
    try:
        data = json.loads(source.read_text(encoding='utf-8'))
        _validate_seed(data)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError('Не удалось прочитать данные: ' + str(exc)) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='arena-', suffix='.sqlite3', dir=destination.parent)
    os.close(handle)
    temporary = Path(temporary)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(SCHEMA)
        for entry in data['concepts']:
            connection.execute('INSERT INTO concepts VALUES(?,?,?,?,?)', tuple(entry.get(k) for k in ('id','lemma','acc','gender','definition')))
            forms = set(f.lower().replace('ё','е').strip() for f in entry['forms'])
            connection.executemany('INSERT INTO forms VALUES(?,?,?,?)', [(form,entry['id'],'unknown','unannotated') for form in forms])
            connection.executemany('INSERT INTO groups VALUES(?,?)', [(entry['id'],category) for category in set(entry['categories'])])
        for entry in data['facts']:
            connection.execute('INSERT INTO facts VALUES(?,?,?,?,?,?)', tuple(entry.get(k) for k in ('id','subject','predicate','object','value','reason')))
        for entry in data['knowledge']:
            connection.execute('INSERT INTO knowledge VALUES(?,?,?,?,?,?)',
                               (entry['id'],entry['kind'],entry['topic'],json.dumps(entry['attributes'],ensure_ascii=False),json.dumps(entry['clauses'],ensure_ascii=False),entry['source']))
        connection.executemany('INSERT INTO metadata VALUES(?,?)', [('schema_version','1'),('provenance',data['provenance'])])
        connection.commit()
        connection.close()
        connection = None
        validate_database(temporary)
        # Windows rename refuses an existing target; hard links need extra rights in some workspaces.
        if os.name == 'nt':
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
        return destination
    except (sqlite3.Error, OSError) as exc:
        raise ValueError('Не удалось создать базу: ' + str(exc)) from exc
    finally:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)


def validate_database(path):
    connection = None
    try:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        connection.execute('SELECT id,lemma,acc,gender,definition FROM concepts LIMIT 0')
        connection.execute('SELECT form,concept,pos,features FROM forms LIMIT 0')
        connection.execute('SELECT id,subject,predicate,object,value,reason FROM facts LIMIT 0')
        connection.execute('SELECT concept,category FROM groups LIMIT 0')
        connection.execute('SELECT id,kind,topic,attributes_json,clauses_json,source FROM knowledge LIMIT 0')
        version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version != ('1',):
            raise ValueError('Неподдерживаемая версия базы')
        for attributes, clauses in connection.execute('SELECT attributes_json,clauses_json FROM knowledge'):
            if not isinstance(json.loads(attributes), dict) or not isinstance(json.loads(clauses), list):
                raise ValueError('Некорректный JSON знаний')
        return {'schema_version':1, **{name:connection.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in ('concepts','facts','knowledge')}}
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        raise ValueError('Несовместимая база: ' + str(exc)) from exc
    finally:
        if connection is not None:
            connection.close()


def ensure_demo_database():
    destination = ROOT / 'data/demo.sqlite3'
    if not destination.exists():
        build_database(ROOT / 'data/demo.json', destination)
    validate_database(destination)
    return destination
