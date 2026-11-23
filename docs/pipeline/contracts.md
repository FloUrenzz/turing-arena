# Контракты движка v1 — 2026-11-23

Пользователь принял уточнённый план и поручил делать движок. Запись/YouTube переданы сокоманднику. Исполняемая система локальная, Python 3.11 и stdlib; production не импортирует spike.

## Границы модулей

- `arena/data.py`: проверка и создание SQLite из подготовленного локального JSON.
- `arena/lexicon.py`: чтение v0/v1 SQLite, поиск словоформ/понятий и фактов. v0 — четыре таблицы текущего spike; v1 дополнительно metadata и knowledge.
- `arena/engine.py`: `generate(question, state, db_path, seed=None) -> dict`. Чистая относительно состояния функция: входное state не меняется, БД только читается. Ответ не является уже опубликованным.
- `arena/models.py`: `initial_state() -> dict`, `apply_reply(state, question, reply) -> dict`; новое состояние создаётся после успешной передачи ответа.
- `arena/runtime.py`: изоляция вычисления в процессе, timeout, задержка, однократная доставка, применение памяти.
- `main.py`: локальная CLI-оболочка, stdout содержит только ответ; диагностика/время идут в stderr. Исследовательские флаги явно отмечаются.

## State: JSON-совместимый объект

```python
{
  "turn": 0,                         # int >= 0
  "history": [],                     # последние <=32 question/text/intent/topic
  "first_question": None,            # первая публично обработанная формулировка
  "last_topic": None,                # concept/topic id либо None
  "last_intent": None,
  "user_name": None,
  "user_preferences": {},            # concept -> число, не предпочтения персонажа
}
```

## Ответ generate

```python
{
  "text": "...",                     # непустой русский текст, <=300 символов
  "intent": "explanation",           # preference/choice/reason/identity/recall/math/text/
                                      # explanation/advice/social/greeting/unknown/definition/acknowledgment
  "topic": "rainbow",                # str|None
  "concepts": ["rainbow"],
  "facts": ["rainbow_cause"],
  "fallback": False,
  "trace": ["..."],                  # техническое объяснение, не текст зрителю
  "updates": {"user_name": "Дина", "user_preferences": {"coffee": 1}},
}
```

Поля updates необязательны; неизменные факты персонажа не входят в updates. Одна публичная выдача означает один apply_reply. При ошибке доставки memory не меняется. Запасная реплика не применяет непринятые изменения исходного обработчика.

## Runtime

```python
class Runtime:
    def __init__(self, db_path, *, timed=True, worker_timeout=2.0,
                 seed=None, worker=None): ...
    def respond(self, question, *, request_id=None, sink=None,
                deadline=None) -> dict: ...
```

`worker` — необязательная picklable функция `(question, state, db_path, seed) -> dict` для фактического fault injection в тестах. По умолчанию engine.generate. `deadline` — внешний дедлайн по monotonic либо None. Запуск процесса через Windows-compatible spawn. Обработчик принудительно завершается после worker_timeout; тайм-аут и ошибка дают непустой русский резерв. Подготовка/ожидание измеряются от одного старта. При отсутствии внешнего deadline целевой момент выдачи `clamp(3 + 0.12*len(text) + uniform(-1,1),3,40)` секунд; timed=False — только разработка. Внешний дедлайн сильнее искусственной задержки, резерв на передачу 2 секунды.

`sink(reply)` вызывается один раз перед изменением state. При None Runtime сохраняет ответ и возвращает его; это логическая доставка в API, CLI передаёт sink с печатью. Повторный request_id с тем же question не вызывает sink и не меняет memory; с другим question вызывает ValueError. Результат runtime дополнительно содержит elapsed, target_seconds, status(ok/timeout/error), duplicate. При повторной ошибке доставки сохраняется подготовленный ответ: повтор не должен генерировать иной вариант. В памяти <=128 идентификаторов; активное испытание не может бесконечно накапливать данные.

## БД v1

Обязательные таблицы совместимы с текущими concept/form/fact/group именами:

```sql
CREATE TABLE concepts(id TEXT PRIMARY KEY, lemma TEXT NOT NULL, acc TEXT NOT NULL,
                      gender TEXT, definition TEXT);
CREATE TABLE forms(form TEXT NOT NULL, concept TEXT NOT NULL, pos TEXT, features TEXT,
                   PRIMARY KEY(form, concept));
CREATE TABLE facts(id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL,
                   object TEXT NOT NULL, value REAL, reason TEXT);
CREATE TABLE groups(concept TEXT NOT NULL, category TEXT NOT NULL,
                    PRIMARY KEY(concept, category));
CREATE TABLE knowledge(id TEXT PRIMARY KEY, kind TEXT NOT NULL, topic TEXT NOT NULL,
                       attributes_json TEXT NOT NULL, clauses_json TEXT NOT NULL,
                       source TEXT NOT NULL);
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

`clauses_json` — список коротких смысловых частей, не полные пары вопрос/ответ. `attributes_json` — контекст, выбранный правилами. Разбор JSON не выполняет Python-код. Имя/роль/предпочтения персонажа читаются из facts; `subject=self, predicate=likes`, value >0 нравится, <0 не нравится. Лексические формы нормализованы lower, ё->е; неизвестная морфология помечается unknown/unannotated.

Локальный seed JSON: объект с `schema_version:1`, `provenance:str`, `concepts:list`, `facts:list`, `knowledge:list`. Concept: id,lemma,acc,gender,definition,forms:list[str],categories:list[str]. Fact: id,subject,predicate,object,value,reason. Knowledge: id,kind,topic,attributes:dict,clauses:list[str],source:str. Нет обязательных переменных окружения, ключей или .env. Данные подготовлены заранее; стандартная БД `data/demo.sqlite3`, seed `data/demo.json`.

API data: `build_database(source: Path|str, destination: Path|str) -> Path`, `ensure_demo_database() -> Path`, `validate_database(path) -> dict` (schema_version, concepts,facts,knowledge). ROOT вычисляется относительно файла пакета. Несовместимая БД/JSON — ValueError с понятной ошибкой, не тихое обнуление пользовательских данных. Существующую БД не перезаписывать неявно.

## Первая версия знаний

Стабильные topics/knowledge ids для движка: rainbow_cause, rainbow_conditions, rainbow_colors (kind=explanation, topic=rainbow); winter_city, astana_winter, summer_city, newcomer_generic (kind=advice); late_apology, late_no_apology, self_late, exam_failure, success, forgotten_birthday (kind=social). kind/topic знания могут совпадать с id, кроме rainbow. clauses — 2–4 самостоятельные короткие русские части; движок выбирает и комбинирует их по слотам. Не добавлять полные контрольные вопросы в маршрутизацию.

Источники научных и климатических фактов: NOAA What Causes a Rainbow, официальный Visit Astana Weather Condition; источники указывать в source. Социальные примеры и демо-персонаж — демонстрационные данные, подготовленные с помощью ИИ, без приписывания авторства участникам. Runtime никогда не обращается к URL источников.

## Ошибки и проверяемые границы

- Неизвестные формы/отношения => уточнение или честное незнание; один знакомый термин не достаточен для произвольного ответа.
- База/процесс/время => supervisor резерв; исключения и внутренние пути не показываются зрителю.
- Неверный request_id => ValueError в интеграционном API, не новый ответ.
- Чрезмерный ввод/операция => ограниченный русский ответ, без eval/exec.
- Лимит длины проверяется после сборки; нет сырого среза середины фразы. Нормализация управляющих символов перед выдачей.
- Никаких обещаний пережить сбой всей ОС/оборудования и универсально понять любой вопрос.

## Корпус сокомандника (2026-11-23)

Исходники datasets/*.xlsx неизменяемы. Это пары реплика–ответ, не морфологический словарь. Заголовок на строке 6: №, Тема, До этого в разговоре, Что пишут, Ответ бота, [Источник], Решение, Твоя правка, Примечание. Импорт не исполняет формулы. Статус Подтверждаю активен; Правка активен только при непустой Твоей правке; Проверить/Убрать неактивны. Импорт отдельным подготовительным шагом, во время разговора читается только SQLite.

`arena.corpus_import.build_corpus(sources, destination) -> dict`: stdlib XLSX -> новая SQLite, существующую не перезаписывать. Исключения ValueError с путём/строкой при невалидных данных; оригиналы неизменны. Таблицы corpus_sources(id,filename,sha256,sheet), corpus_replies(id,source_id,row_number,example_id,topic,context,prompt,answer,status,approved,origin,note), corpus_metadata(key,value). Итог dict содержит rows, approved, pending, sources; sha256 фиксируется для каждого файла. Все тексты параметризованным SQL. Максимум 300 codepoints и UTF16 units для активного ответа, русский текст; строки без пар и неизвестные статусы не пропускать молча.

`arena.corpus.Corpus(path).match(question, history) -> dict | None`: только активные записи с достаточным совпадением. Отрицание, роли, числа и тип вопроса не терять. Контекстные строки допустимы только при совпадающем предыдущем диалоге с проверкой роли. Память, арифметика, инструкции и противоречащие персонажу предпочтения не подменяются статическим ответом. Все 350 записей сохраняются с происхождением; 200 Проверить не участвуют в выдаче. Пример №20 (утверждение географии в теме Игра) помещён в карантин до проверки содержания.

Runtime `--corpus PATH` выбирает SQLite корпуса, `--no-corpus` отключает его; без флага используется data/dialogue.sqlite3, если файл существует. Явно указанный отсутствующий/невалидный файл — ошибка запуска. Нет автоматической сетевой загрузки или импорта XLSX в раунде. Источники форм/фактов по-прежнему выбираются --db. Основные вычисления/память/смысловые правила имеют приоритет; корпус расширяет неизвестные бытовые реплики и приветствия. Диагностика содержит row/source/score, сценический вывод только текст.

После независимого аудита: обязательное совпадение ordered content tokens после aliases/stem/STOP; новые или удалённые значимые слова и их перестановки отклоняются. Это ограниченный перенос формулировок, не универсальный семантический поиск. Исходные пять ошибок сохраняются в audit-corpus-v2.md/audit.json.
