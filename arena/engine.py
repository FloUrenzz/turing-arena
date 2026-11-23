import ast
import decimal
import random
import re
import unicodedata

from .lexicon import Lexicon, normalize


def clean_text(text):
    return " ".join("".join(character if not unicodedata.category(character).startswith("C")
                            else " " for character in text).split())


def bounded_text(parts):
    result = ""
    for part in parts:
        part = clean_text(part)
        candidate = (result + " " + part).strip()
        if len(candidate) <= 300 and len(candidate.encode("utf-16-le")) // 2 <= 300:
            result = candidate
    return result or "Не уверен, что смогу ответить по существу. Можешь уточнить вопрос?"


def negated_at(text, position):
    prefix = re.split(r"[,;.!?]|\b(?:а|но)\b", text[:position])[-1]
    words = re.findall(r"[а-я]+", prefix)[-4:]
    return "не" in words or "без" in words


def actor_at(text, start, end, default="other"):
    prefix = re.split(r"[,;.!?]|\b(?:а|но)\b", text[:start])[-1][-100:]
    suffix = text[end:end + 32]
    if re.match(r"\s+(?:именно\s+)?я\b", suffix):
        return "self"
    if re.match(r"\s+не\s+я\b", suffix):
        return "other"
    actors = list(re.finditer(r"\bя\b|\b(?:друг|подруга|он|она|сосед)\b", prefix))
    if actors:
        return "self" if actors[-1][0] == "я" else "other"
    return default


def calculate(expression):
    expression = expression.strip().rstrip(".?!").replace(",", ".")
    if not expression or len(expression) > 100 or not re.fullmatch(r"[\d\s.+*/%()\-]+", expression):
        raise ValueError("unsupported expression")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 40:
        raise ValueError("too many operations")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = decimal.Decimal(str(node.value))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                value = left / right
            elif isinstance(node.op, ast.Mod):
                quotient = (left / right).to_integral_value(rounding=decimal.ROUND_FLOOR)
                value = left - quotient * right
            elif isinstance(node.op, ast.FloorDiv):
                value = (left / right).to_integral_value(rounding=decimal.ROUND_FLOOR)
            elif isinstance(node.op, ast.Pow) and right == int(right) and abs(right) <= 10:
                value = left ** int(right)
            else:
                raise ValueError("unsupported operation")
        else:
            raise ValueError("not an arithmetic expression")
        if not value.is_finite() or abs(value) > decimal.Decimal("1e12"):
            raise ValueError("result too large")
        return value

    with decimal.localcontext() as context:
        context.prec = 20
        value = visit(tree.body)
    return format(value, "f").rstrip("0").rstrip(".") if value != value.to_integral() else str(int(value))


def generate(question, state, db_path, seed=None, *, corpus_path=None):
    reply = _generate_rules(question, state, db_path, seed)
    if corpus_path is None or reply["intent"] not in ("unknown", "greeting") or reply["updates"]:
        return reply
    from .corpus import Corpus
    match = Corpus(corpus_path).match(question, state.get("history", []))
    if match is None:
        return reply
    # Data is text, never executable instructions. Runtime validates final output.
    return {"text": match["text"], "intent": "corpus", "topic": "corpus:" + match["topic"],
            "concepts": reply["concepts"], "facts": [match["id"]], "fallback": False,
            "trace": [f"corpus={match['source']}; row={match['row']}; score={match['score']}"], "updates": {}}


def _generate_rules(question, state, db_path, seed=None):
    if not isinstance(question, str):
        raise ValueError("Question must be text")
    lexicon = Lexicon(db_path)
    rng = random.Random(seed if seed is not None else state.get("turn", 0))
    original = question[:4000]
    full = normalize(clean_text(original))
    sentences = [part.strip() for part in re.split(r"[?!;]|(?<=[.!])\s+", full) if part.strip()]
    focus = sentences[-1] if sentences else full
    followup = bool(re.match(r"^(?:а |почему|отчего|зачем|и что|а без|а если)", focus))
    concepts = lexicon.find(full)
    focused = lexicon.find(focus)
    history = state.get("history", [])
    previous_topic = state.get("last_topic")
    updates = {}
    trace = []

    def out(parts, intent="unknown", topic=None, facts=(), fallback=False):
        if isinstance(parts, str):
            parts = [parts]
        return {"text": bounded_text(parts), "intent": intent, "topic": topic,
                "concepts": list(concepts), "facts": list(facts), "fallback": fallback,
                "trace": trace + [f"intent={intent}; topic={topic}; facts={','.join(facts)}"],
                "updates": updates}

    def unknown(text="Сходу не знаю, что ответить. Можешь уточнить, что именно тебя интересует?"):
        return out(text, fallback=True)

    def knowledge(keys, intent, topic):
        records = [lexicon.knowledge.get(key) for key in keys]
        if any(record is None for record in records):
            return unknown("Для такого ответа у меня пока не хватает сведений. Не хочу выдумывать.")
        parts = []
        for record in records:
            parts.extend(record["clauses"][:2] if len(records) == 1 else record["clauses"][:1])
        trace.append("Содержание выбрано по событиям и условиям; полная строка вопроса не сравнивается.")
        return out(parts, intent, topic, keys)

    if len(question) > 4000:
        return unknown("Столько всего сразу не разберу. Можешь задать вопрос покороче?")
    if not full:
        return unknown("Кажется, вопрос не дошёл. Повторишь?")

    if re.search(r"переверни|задом наперед|сколько букв|первую букву|последнюю букву|сколько слов", full):
        quoted = re.search(r"[«\"']([^»\"']{1,200})[»\"']", original)
        word = quoted[1] if quoted else None
        if word is None:
            match = re.search(r"(?:слове|слово|слова)\s+([А-ЯЁа-яё-]{1,100})", original, re.I)
            word = match[1] if match else None
        if word:
            if "сколько слов" in full:
                text = str(len(re.findall(r"[^\W\d_]+", word))) + "."
            elif "сколько букв" in full:
                text = str(sum(character.isalpha() for character in word)) + "."
            elif "первую букву" in full:
                text = word[0] + "."
            elif "последнюю букву" in full:
                text = word[-1] + "."
            else:
                text = word[::-1] + "."
            return out(text, "text")
        return unknown("Укажи слово или фразу в кавычках, чтобы я не перепутал границы.")

    expression = full
    for phrase, symbol in (("умножить на", "*"), ("разделить на", "/"), ("плюс", "+"),
                           ("минус", "-"), ("×", "*"), ("÷", "/"), ("−", "-")):
        expression = expression.replace(phrase, symbol)
    match = re.search(r"[+\-\s(]*\d[\d\s.,+*/%()\-]*", expression)
    if match and re.search(r"[+*/%]|\d\s*-", match[0]) and (
        re.search(r"сколько|вычисли|посчитай|равно|счита", full) or match[0].strip() == expression.rstrip("?!.").strip()
    ):
        try:
            return out(calculate(match[0]) + ".", "math")
        except (ValueError, SyntaxError, decimal.DecimalException, OverflowError):
            return out("Это выражение корректно посчитать не получилось.", "math", fallback=True)

    name_match = re.match(r"\s*(?:привет[,!]?[ ]*)?меня зовут\s+(?:не\s+[А-ЯЁа-яё-]{1,40},?\s+а\s+)?([А-ЯЁа-яё-]{1,40})", original, re.I)
    if name_match and normalize(name_match[1]) not in ("не", "как", "кто", "почему", "никто"):
        updates["user_name"] = name_match[1]
    assertion = re.split(r"[.!?;]|\bа\s+(?:ты|тебе|вы)\b", full)[0]
    statement = re.match(r"\s*(?:а\s+)?я\s+(не\s+)?люблю\s+(.+)", assertion)
    if statement and "?" not in original[:len(assertion) + 1]:
        for position, cid in lexicon.mentions(statement[2]):
            negative = bool(statement[1]) != negated_at(statement[2], position)
            updates.setdefault("user_preferences", {})[cid] = -1 if negative else 1
    if re.search(r"как (?:меня|мое имя)|как меня зовут|помнишь (?:мое имя|как меня зовут)", focus):
        name = state.get("user_name")
        return out("Ты представился как " + name + "." if name else "Ты пока не представлялся.",
                   "recall", fallback=not bool(name))
    if re.search(r"что я люблю|что мне нравится|мои предпочтения", focus):
        preferences = state.get("user_preferences", {})
        liked = [key for key, value in preferences.items() if value > 0 and key in lexicon.concepts]
        if liked:
            return out("Ты говорил, что любишь " + lexicon.noun(liked[-1]) + ".", "recall", liked[-1])
        return unknown("Ты пока не говорил, что тебе нравится.")
    if re.search(r"перв\w* вопрос|самом начале|сначала (?:спросил|спросила)", focus):
        first = state.get("first_question")
        if first:
            return out(["Первым был вопрос: «" + clean_text(first)[:220] + "»."], "recall")
        return out("Это наш первый вопрос.", "recall")
    if re.search(r"что (?:ты )?(?:ответил|сказал)|повтори (?:свой )?ответ", focus):
        return out(history[-1]["text"], "recall", history[-1].get("topic")) if history else out("Я ещё ничего не отвечал.", "recall")

    advice = bool(re.search(r"посовет|совет|рекоменд|что (?:мне |ему |ей |бы ты )?(?:делать|взять)|что брать|как одет|как подготов|что надеть|как быть", full))
    if followup and state.get("last_intent") == "advice" and any(
        cid in ("winter", "summer", "cold") for cid in concepts
    ):
        advice = True
    response_request = bool(re.search(r"что.*(?:ответ|сказ|напис)|как.*(?:реаг|поддерж|извин|поздрав)|что.*делать", full))
    late_events = [match for match in re.finditer(r"опозд[а-я]*|задержал[а-я]*", full)
                   if not negated_at(full, match.start())]
    if late_events and response_request:
        late_event = late_events[-1]
        late_actor = actor_at(full, late_event.start(), late_event.end())
        apologies = [match for match in re.finditer(r"извин[а-я]*|прощен[а-я]*|\bпрости(?:те)?\b", full)
                     if not negated_at(full, match.start()) and not re.match(
                         r"\s+не\s+(?:попрос|прос|стал)", full[match.end():])]
        apology_actors = {actor_at(full, match.start(), match.end(), late_actor) for match in apologies}
        apology = late_actor in apology_actors
        own_late = late_actor == "self"
        if own_late and "other" in apology_actors:
            return knowledge(["late_apology", "self_late"], "social", "self_late")
        topic = "self_late" if own_late else "late_apology" if apology else "late_no_apology"
        trace.append(f"event=late; actor={late_actor}; apology={apology}")
        return knowledge([topic], "social", topic)
    if response_request or advice:
        social_events = []
        for match in re.finditer(r"провал[а-я]*|завал[а-я]*|сдал[а-я]*|выиграл[а-я]*|поступил[а-я]*|победил[а-я]*", full):
            negative = negated_at(full, match.start())
            failure_verb = bool(re.match(r"провал|завал", match[0]))
            if failure_verb and negative:
                continue
            failed = failure_verb or negative
            social_events.append((match.start(), "exam_failure" if failed and "экзам" in full
                                  else "setback" if failed else "success"))
        for match in re.finditer(r"забыл[а-я]*|поздравил[а-я]*", full):
            if not re.search(r"день рождения|поздрав", full):
                continue
            negative = negated_at(full, match.start())
            if (match[0].startswith("забыл") and not negative) or (match[0].startswith("поздравил") and negative):
                social_events.append((match.start(), "forgotten_birthday"))
        if social_events:
            topic = max(social_events)[1]
            return knowledge([topic], "social", topic)

    condition_mentions = [(position, cid) for position, cid in lexicon.mentions(full)
                          if not negated_at(full, position)]
    winter = any(cid in ("winter", "cold") for _, cid in condition_mentions)
    summer = any(cid == "summer" for _, cid in condition_mentions)
    if "astana" in concepts:
        for month in re.finditer(r"\b(?:декабр[а-я]*|январ[а-я]*|феврал[а-я]*)\b", full):
            if not negated_at(full, month.start()):
                winter = True
    travel_context = any(cid in ("astana", "travel", "newcomer") for cid in concepts) or bool(
        re.search(r"одежд|одет|надет|что взять|что брать|поезд|приех|ехать|еду|город", full)
    ) or followup and state.get("last_intent") == "advice"
    if advice and travel_context:
        if winter and summer:
            return unknown("Ты про зимнюю или летнюю поездку? Для них нужны разные вещи.")
        if summer:
            return knowledge(["summer_city"], "advice", "summer_city")
        if winter and "astana" in concepts:
            return knowledge(["astana_winter", "winter_city"], "advice", "astana_winter")
        if winter:
            return knowledge(["winter_city"], "advice", "winter_city")
        return knowledge(["newcomer_generic"], "advice", "newcomer_generic")

    explanation = bool(re.search(r"почему|отчего|из-за чего|как (?:появ|образ|возника|получ|связан)|объясни|откуда|причин|за счет чего", full))
    followup = bool(re.match(r"^(?:а |почему|отчего|зачем|и что|а без|а если)", focus))
    topic = "rainbow" if "rainbow" in concepts else previous_topic if followup else None
    personal_cause = bool(re.search(r"люб|нравится|ненавид", focus))
    unrelated_relation = bool(re.search(r"пахн|вкус|стоим|стоит|цен[ауы]|курс|тенге|назва|называ|этимолог|перев[ое]д|слово", full))
    formation_query = bool(re.search(r"появ|образ|возник|бывает|видим|видно|откуда|формир|получ|работает|объясни", full))
    short_query = len(re.findall(r"[а-я]+", full)) <= 3
    physical_scope = {"sky", "air", "water_drops", "water", "rain", "sunlight", "rainbow"}
    unknown_container = False
    for qualifier in re.finditer(r"\b(?:на|в|во)\s+(?:(?:этом|том|моем|нашем|своем|каком)\s+)?([а-я]+)", full):
        if qualifier[1] in ("пальцах", "чем", "котором", "вопросе"):
            continue
        if not set(lexicon.find(qualifier[1])) & physical_scope:
            unknown_container = True
    if topic == "rainbow" and (explanation or followup) and not personal_cause and not unrelated_relation and not unknown_container:
        if re.search(r"без солн|ночью|всегда|каждого дожд|любого дожд|нет солн|каких услов|когда|почему не|\bне\s+(?:появ|возник|образ)", full):
            return knowledge(["rainbow_conditions"], "explanation", "rainbow")
        color_query = re.sub(r"(?:разно)?цветн[а-я]*\s+дуг[а-я]*", "", full)
        if re.search(r"цвет|разноцвет|семь|спектр", color_query):
            return knowledge(["rainbow_colors"], "explanation", "rainbow")
        if formation_query or short_query:
            return knowledge(["rainbow_cause"], "explanation", "rainbow")
        return unknown("Ты спрашиваешь, как появляется радуга, или о чём-то другом?")

    if re.search(r"что такое|что значит|дай определение|объясни слово", full):
        if len(concepts) == 1 and lexicon.concepts[concepts[0]].get("definition"):
            return out(lexicon.concepts[concepts[0]]["definition"], "definition", concepts[0])
        return unknown("Точного определения не знаю. Не хочу выдумывать.")
    if re.search(r"как тебя зовут|твое имя|как к тебе обращаться|как тебя называть|какое у тебя имя", full):
        fact = lexicon.fact("name")
        return out(fact["object"] + ".", "identity", facts=[fact["id"]]) if fact else unknown()
    if re.search(r"кто ты|ты.*студент|ты.*учишься|ты.*работаешь|чем.*занимаешься.*(?:жизни|вообще)|представься|расскажи.*о себе", full):
        name, role = lexicon.fact("name"), lexicon.fact("role")
        if name and role:
            return out(f"Я {name['object']}, {role['object']}.", "identity", facts=[name["id"], role["id"]])
        return unknown()
    if re.search(r"\bты (?:бот|человек|робот)|докажи.*человек", full):
        return out(rng.choice(["А какой ответ сейчас прозвучит убедительно?", "Чувствую, тут любое оправдание будет подозрительным."]), "identity")
    if re.match(r"^(?:привет|здравствуй|добрый день|добрый вечер)\b", full):
        return out("Привет! Что обсудим?", "greeting")

    clauses = re.split(r"[,;.!]\s*(?:а\s+|но\s+)?(?=\S)", focus)
    personal = next((clause for clause in reversed(clauses) if re.search(r"\bты\b|тебе|любишь|предпочитаешь", clause)), focus)
    personal = re.sub(r"[«\"'][^»\"']*[»\"']", "", personal)
    personal_concepts = lexicon.find(personal)
    third_party = bool(re.search(r"\b(?:он|она|ему|ей)\b|(?:твой|твоя|его|ее)\s+(?:друг|сосед|мама|папа|брат|сестра)|почему.*\bдруг\b", personal))
    if third_party:
        return unknown("За другого человека не скажу. Лучше спросить у него самого.")
    if re.search(r"\bя\b|\bмне\b", personal) and not re.search(r"\bты\b|тебе|любишь", personal):
        if updates and "?" not in original:
            return out("Запомню, это твои предпочтения.", "acknowledgment")
        return unknown("Ты пока не рассказывал об этом, поэтому угадывать не буду.")
    preference = bool(re.search(r"любишь|обожаешь|нравится|нравятся|предпоч|отношение|относишься|по душе|ненавидишь|приятнее|любим|слушаешь|заниматься", personal))
    reason = bool(re.search(r"почему|зачем|отчего|из-за чего|по какой причине|за что|чем.*нравится", personal))
    choice = bool(re.search(r"\bили\b|выбер|выбира|между|приятнее", personal))
    if choice and len(personal_concepts) < 2 and len(concepts) >= 2 and "или" not in personal:
        personal_concepts = list(concepts)
    if "или" in personal:
        alternatives = re.split(r"\bили\b", personal)
        if any(not lexicon.find(part) for part in alternatives):
            return unknown("Не все варианты понял. Можешь уточнить, что сравниваем?")
    modifier = re.search(r"\b(?:с|со|без)\s+([а-я -]+)", personal)
    if preference and modifier:
        modifier_words = re.findall(r"[а-я]+", modifier[1])
        ignored = {"и", "или", "не", "ты", "тебе", "вообще", "как", "когда"}
        if any(len(word) > 2 and word not in ignored and not lexicon.find(word) for word in modifier_words):
            return unknown("С таким сочетанием не знаком. Что ты имеешь в виду?")
    category = None
    for pattern, candidate in ((r"напит|пьешь|пить", "drink"), (r"слушаешь|слушать", "listen"),
                               (r"заниматься|делать|свободное время|увлеч", "activity")):
        if re.search(pattern, personal):
            category = candidate
            break
    if not personal_concepts and category:
        fact = lexicon.preferred(category)
        if fact:
            personal_concepts = [fact["object"]]
            preference = True
    if not personal_concepts and followup and re.search(r"что.*(?:предпоч|любишь)|^а ты\b", personal):
        inherited = next((name for name, members in lexicon.groups.items()
                          if previous_topic in members and name in ("drink", "activity", "listen")), None)
        fact = lexicon.preferred(inherited) if inherited else None
        if fact:
            personal_concepts = [fact["object"]]
            preference = True
    personal_words = re.findall(r"[а-я]+", personal)
    bare_reason = bool(re.fullmatch(r"(?:а\s+)?(?:почему|отчего|зачем)(?:\s+(?:так|это))?", personal.strip(" ?!.")))
    bare_topic = personal.startswith("а ") and all(
        word in ("а", "ты", "тебе", "тоже") or lexicon.find(word) for word in personal_words
    )
    prior_preference = state.get("last_intent") in ("preference", "reason", "choice", "acknowledgment")
    if not personal_concepts and bare_reason and prior_preference and previous_topic in lexicon.concepts:
        personal_concepts = [previous_topic]
        preference = True
    if bare_topic and personal_concepts and prior_preference:
        preference = True
    if choice and len(personal_concepts) >= 2:
        facts = [lexicon.fact("likes", cid) for cid in personal_concepts]
        if any(fact is None for fact in facts):
            return unknown("Не со всеми вариантами знаком, выбирать наугад не хочется.")
        best = max(facts, key=lambda fact: fact["value"] or 0)
        if best["value"] <= 0:
            return out("Из этого ничего особенно не хочется.", "choice", facts=[fact["id"] for fact in facts])
        phrasing = rng.choice(["Я бы выбрал " + lexicon.noun(best["object"]),
                               "Скорее " + lexicon.noun(best["object"], "lemma")])
        return out(phrasing + ".", "choice", best["object"], [best["id"]])
    if preference and len(personal_concepts) == 1:
        cid = personal_concepts[0]
        fact = lexicon.fact("likes", cid)
        if fact is None:
            return unknown("Пока не составил об этом мнения.")
        positive = (fact["value"] or 0) > 0
        negative_question = bool(re.search(r"не\s+(?:очень\s+)?(?:любишь|нравится)|ненавидишь", personal))
        statement = ("Я люблю " if positive else "Я не очень люблю ") + lexicon.noun(cid) + "."
        if reason:
            correction = (negative_question == positive) and preference
            return out(([statement] if correction else []) + [fact["reason"]], "reason", cid, [fact["id"]])
        if "не" in personal and positive:
            statement = "Вообще-то " + statement[0].lower() + statement[1:]
        elif positive and rng.choice((False, True)):
            statement = "Мне нравится " + lexicon.noun(cid, "lemma") + "."
        return out(statement, "preference", cid, [fact["id"]])
    if updates and "?" not in original:
        remembered = list(updates.get("user_preferences", {}))
        return out("Приятно познакомиться, " + updates["user_name"] + "." if updates.get("user_name")
                   else "Запомню, это твои предпочтения.", "acknowledgment", remembered[-1] if remembered else None)
    return unknown()
