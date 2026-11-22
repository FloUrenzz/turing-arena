from copy import deepcopy


def initial_state():
    return {
        "turn": 0, "history": [], "first_question": None, "last_topic": None,
        "last_intent": None, "user_name": None, "user_preferences": {},
    }


def apply_reply(state, question, reply):
    updated = deepcopy(state)
    updated["turn"] += 1
    if updated["first_question"] is None:
        updated["first_question"] = question[:4000]
    updated["history"] = (updated["history"] + [{
        "question": question[:4000], "text": reply["text"],
        "intent": reply["intent"], "topic": reply.get("topic"),
    }])[-32:]
    updated["last_topic"] = reply.get("topic") if not reply.get("fallback") else None
    updated["last_intent"] = reply["intent"]
    if not reply.get("fallback"):
        updates = reply.get("updates", {})
        if updates.get("user_name"):
            updated["user_name"] = updates["user_name"]
        updated["user_preferences"].update(updates.get("user_preferences", {}))
    return updated
