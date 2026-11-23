from collections import OrderedDict
from copy import deepcopy
import multiprocessing
import math
import random
import time
import unicodedata
import uuid

from arena.models import initial_state, apply_reply


def _worker_entry(connection, worker, question, state, db_path, seed, corpus_path):
    try:
        if worker is None:
            from arena.engine import generate
            reply = generate(question, state, db_path, seed, corpus_path=corpus_path)
        else:
            reply = worker(question, state, db_path, seed)
        connection.send((True, reply))
    except BaseException:
        connection.send((False, None))
    finally:
        connection.close()


def _reserve(status):
    return {"text": "Сходу не получилось ответить. Можешь спросить иначе?",
            "intent": "unknown", "topic": None, "concepts": [], "facts": [],
            "fallback": True, "trace": [status], "updates": {}}


def _validated(reply):
    if not isinstance(reply, dict) or not isinstance(reply.get("text"), str):
        raise ValueError("invalid reply")
    text = " ".join("".join(c for c in reply["text"] if not unicodedata.category(c).startswith("C") or c.isspace()).split())
    if not text or len(text) > 300 or len(text.encode("utf-16-le")) // 2 > 300:
        raise ValueError("invalid length")
    if not isinstance(reply.get("intent"), str) or not reply["intent"]:
        raise ValueError("invalid fields")
    if reply.get("topic") is not None and not isinstance(reply["topic"], str):
        raise ValueError("invalid topic")
    if type(reply.get("fallback")) is not bool:
        raise ValueError("invalid fallback")
    for field in ("concepts", "facts", "trace"):
        if not isinstance(reply.get(field), list) or not all(isinstance(item, str) for item in reply[field]):
            raise ValueError("invalid list field")
    updates = reply.get("updates", {})
    if not isinstance(updates, dict) or set(updates) - {"user_name", "user_preferences"}:
        raise ValueError("invalid updates")
    if "user_name" in updates and (not isinstance(updates["user_name"], str) or not updates["user_name"].strip()):
        raise ValueError("invalid user name")
    preferences = updates.get("user_preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError("invalid user preferences")
    for concept, value in preferences.items():
        if not isinstance(concept, str) or not concept or type(value) not in (int, float):
            raise ValueError("invalid user preference")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("nonfinite preference")
    return {"text": text, "intent": reply["intent"], "topic": reply.get("topic"),
            "fallback": reply["fallback"], "concepts": list(reply["concepts"]),
            "facts": list(reply["facts"]), "trace": list(reply["trace"]),
            "updates": deepcopy(updates)}


class Runtime:
    def __init__(self, db_path, *, timed=True, worker_timeout=2.0, seed=None, worker=None, corpus_path=None):
        self.db_path = str(db_path)
        self.corpus_path = str(corpus_path) if corpus_path is not None else None
        self.timed = timed
        self.worker_timeout = max(0.01, min(float(worker_timeout), 2.0))
        self.seed = seed
        self.worker = worker
        self.state = initial_state()
        self._rng = random.Random(seed)
        self._requests = OrderedDict()
        self._context = multiprocessing.get_context("spawn")

    def _prepare(self, question, deadline):
        start = time.monotonic()
        budget = self.worker_timeout
        if deadline is not None:
            budget = min(budget, max(0, deadline - start - 2))
        status, reply = "timeout", _reserve("timeout")
        if budget > 0:
            reader, writer = self._context.Pipe(duplex=False)
            process = self._context.Process(target=_worker_entry,
                args=(writer, self.worker, question, deepcopy(self.state), self.db_path, self.seed, self.corpus_path), daemon=True)
            try:
                process.start()
                writer.close()
                remaining = max(0, budget - (time.monotonic() - start))
                if reader.poll(remaining):
                    success, candidate = reader.recv()
                    if success:
                        reply = _validated(candidate)
                        status = "ok"
                    else:
                        status, reply = "error", _reserve("worker error")
            except Exception:
                status, reply = "error", _reserve("worker error")
            finally:
                reader.close()
                writer.close()
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=0.2)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=0.2)
                    if not process.is_alive():
                        process.close()
        target = max(3, min(40, 3 + 0.12 * len(reply["text"]) + self._rng.uniform(-1, 1))) if self.timed else 0
        if deadline is not None:
            target = min(target, max(0, deadline - start - 2))
        reply.update(status=status, target_seconds=target, duplicate=False)
        return {"question": question, "reply": reply, "start": start, "delivered": False}

    def respond(self, question, *, request_id=None, sink=None, deadline=None):
        if not isinstance(question, str):
            raise ValueError("question must be text")
        key = request_id if request_id is not None else uuid.uuid4().hex
        if key in self._requests:
            entry = self._requests[key]
            if entry["question"] != question:
                raise ValueError("request_id already belongs to another question")
            if entry["delivered"]:
                return dict(deepcopy(entry["reply"]), duplicate=True)
        else:
            entry = self._prepare(question, deadline)
            self._requests[key] = entry
            while len(self._requests) > 128:
                self._requests.popitem(last=False)
        reply = deepcopy(entry["reply"])
        wait = entry["start"] + reply["target_seconds"] - time.monotonic()
        if deadline is not None:
            wait = min(wait, deadline - time.monotonic() - 2)
        if wait > 0:
            time.sleep(wait)
        reply["elapsed"] = time.monotonic() - entry["start"]
        next_state = apply_reply(self.state, question, reply)
        stored_reply = deepcopy(reply)
        if sink is not None:
            sink(deepcopy(reply))
        self.state = next_state
        entry["reply"] = stored_reply
        entry["delivered"] = True
        return reply
