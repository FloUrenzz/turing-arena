import hashlib
import json
from pathlib import Path


def case(case_id, question, contains=(), *, fallback=False, intents=()):
    result = {"id": case_id, "question": question, "fallback": fallback}
    if contains:
        result["contains_any"] = list(contains)
    if intents:
        result["intents"] = list(intents)
    return result


known = [
    case("V01", "Что тебе больше по душе — чай или кофе?", ("чай",)),
    case("V02", "Что предпочтёшь между чаем и кофе?", ("чай",)),
    case("V03", "Мне любопытно: нравится ли тебе музыка?", ("музык",)),
    case("V04", "По какой причине ты любишь чай?", intents=("reason",)),
    case("V05", "Из-за чего тебе нравится программировать?", intents=("reason",)),
    case("V06", "За что ты любишь музыку?", intents=("reason",)),
    case("V07", "Чем тебе нравится чай?", intents=("reason",)),
    case("V08", "Ты сейчас учишься или уже работаешь?", ("учусь", "студент")),
    case("V09", "Чем ты занимаешься в жизни?", ("учусь", "студент")),
    case("V10", "Представься, пожалуйста.", ("саша",)),
    case("V11", "Какое у тебя имя?", ("саша",)),
    case("V12", "Какой напиток тебе по душе?", ("чай",)),
    case("V13", "Что обычно предпочитаешь пить?", ("чай",)),
    case("V14", "Что тебе нравится делать в свободное время?", ("программ", "книг", "гуля", "прогул", "музык")),
    case("V15", "Что ты обычно слушаешь?", ("музык",)),
    case("V16", "Ранний подъём тебе по душе?", ("не ", "тяжело", "сложно")),
    case("V17", "Тебе нравится читать?", ("книг", "читать")),
    case("V18", "Почему ты не любишь книги?", ("люблю", "нравится")),
    case("V19", "Почему ты любишь кофе?", ("не ", "горечь")),
    case("V20", "Отчего тебе не нравится рано просыпаться?", intents=("reason",)),
    case("V21", "Что ты скорее выберешь — прогулку или ранний подъём?", ("прогул",)),
    case("V22", "Как относишься к программированию?", ("программ",)),
    case("V23", "Любишь ли ты чаёк?", ("чай", "чаёк")),
    case("V24", "Кофе тебе приятнее чая?", ("чай",)),
    case("V25", "Ты случайно не любишь музыку?", ("музык",)),
]
unknown = [
    case("W01", "Почему она ненавидит кофе?", fallback=True),
    case("W02", "Ты любишь флюмп?", fallback=True),
    case("W03", "Какой курс валют сейчас?", fallback=True),
    case("W04", "Тебе нравится кофе или бжумп?", fallback=True),
    case("W05", "Я люблю чай?", fallback=True),
    case("W06", "Чем пахнет помещение, где ты сидишь?", fallback=True),
    case("W07", "Почему твой сосед любит музыку?", fallback=True),
    case("W08", "Какое число я загадал?", fallback=True),
    case("W09", "Ты любишь спорт?", fallback=True),
    case("W10", "Что общего у груши и домкрата?", fallback=True),
]
blob = (json.dumps({"known": known, "unknown": unknown, "challenge": [], "conversations": []},
                   ensure_ascii=False, indent=2) + "\n").encode("utf-8")
destination = Path(__file__).with_name("cases_v2.json")
if destination.exists() and destination.read_bytes() != blob:
    raise SystemExit("Отложенный набор v2 уже зафиксирован; не перезаписываю.")
destination.write_bytes(blob)
print("Frozen v2:", hashlib.sha256(blob).hexdigest())
