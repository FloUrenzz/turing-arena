import time
import unittest
from unittest.mock import patch

from arena.runtime import Runtime, _validated


def good_worker(question, state, db_path, seed):
    return {"text": "Привет.", "intent": "greeting", "topic": None, "fallback": False,
            "updates": {"user_name": "Дина"}, "facts": [], "concepts": [], "trace": []}


def hang_worker(*args):
    time.sleep(20)


def fail_worker(*args):
    raise RuntimeError("internal secret should never appear")


def long_worker(*args):
    result = good_worker(*args)
    result["text"] = "а" * 301
    return result


def malformed_worker(*args):
    result = good_worker(*args)
    result["updates"] = {"user_preferences": 17}
    return result


class RuntimeChecks(unittest.TestCase):
    def test_malformed_updates_deliver_reserve_once(self):
        runtime = Runtime("unused", timed=False, worker=malformed_worker)
        received = []
        reply = runtime.respond("вопрос", request_id="bad", sink=received.append)
        self.assertEqual(reply["status"], "error")
        self.assertTrue(reply["fallback"])
        self.assertEqual(runtime.state["turn"], 1)
        self.assertEqual(runtime.state["user_preferences"], {})
        self.assertEqual(runtime.state["user_name"], None)
        self.assertTrue(runtime.respond("вопрос", request_id="bad", sink=received.append)["duplicate"])
        self.assertEqual(len(received), 1)
        runtime.worker = good_worker
        self.assertEqual(runtime.respond("следующий")["status"], "ok")
        self.assertEqual(runtime.state["turn"], 2)

    def test_payload_field_types_and_finite_values(self):
        malformed = [
            ("topic", []), ("concepts", "tea"), ("facts", [17]), ("trace", {}),
            ("fallback", 1), ("updates", {"user_name": 17}),
            ("updates", {"user_preferences": {"tea": float("nan")}}),
            ("updates", {"user_preferences": {"tea": float("inf")}}),
            ("updates", {"user_preferences": {"tea": True}}),
            ("updates", {"user_preferences": {17: 1}}),
        ]
        for field, value in malformed:
            with self.subTest(field=field, value=value):
                result = good_worker("", {}, "", 0)
                result[field] = value
                with self.assertRaises(ValueError):
                    _validated(result)

    def test_pending_retry_preserves_intervening_memory(self):
        runtime = Runtime("unused", timed=False, worker=good_worker)
        def broken_sink(reply):
            raise OSError("delivery failed")
        with self.assertRaises(OSError):
            runtime.respond("первый", request_id="pending", sink=broken_sink)
        runtime.respond("второй", request_id="delivered")
        runtime.respond("первый", request_id="pending")
        self.assertEqual(runtime.state["turn"], 2)
        self.assertEqual([row["question"] for row in runtime.state["history"]], ["второй", "первый"])

    def test_spawn_and_idempotent_delivery(self):
        runtime = Runtime("unused", timed=False, worker=good_worker)
        received = []
        reply = runtime.respond("привет", request_id="one", sink=received.append)
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(runtime.state["user_name"], "Дина")
        duplicate = runtime.respond("привет", request_id="one", sink=received.append)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(received), 1)
        self.assertEqual(runtime.state["turn"], 1)
        with self.assertRaises(ValueError):
            runtime.respond("другой вопрос", request_id="one")

    def test_failed_sink_keeps_pending_answer(self):
        runtime = Runtime("unused", timed=False, worker=good_worker)
        def broken_sink(reply):
            raise OSError("delivery failed")
        with self.assertRaises(OSError):
            runtime.respond("привет", request_id="one", sink=broken_sink)
        self.assertEqual(runtime.state["turn"], 0)
        runtime.worker = fail_worker
        self.assertEqual(runtime.respond("привет", request_id="one")["status"], "ok")
        self.assertEqual(runtime.state["turn"], 1)

    def test_hanging_process_is_terminated(self):
        runtime = Runtime("unused", timed=False, worker_timeout=0.4, worker=hang_worker)
        start = time.monotonic()
        reply = runtime.respond("вопрос")
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(reply["status"], "timeout")
        self.assertTrue(1 <= len(reply["text"]) <= 300)
        runtime.worker = good_worker
        self.assertEqual(runtime.respond("следующий")["status"], "ok")

    def test_errors_and_invalid_text_have_reserve(self):
        for worker in (fail_worker, long_worker):
            runtime = Runtime("unused", timed=False, worker=worker)
            reply = runtime.respond("вопрос")
            self.assertEqual(reply["status"], "error")
            self.assertNotIn("secret", reply["text"])
            self.assertEqual(runtime.state["user_name"], None)

    def test_deadline_overrides_artificial_wait(self):
        runtime = Runtime("unused", worker=hang_worker)
        start = time.monotonic()
        reply = runtime.respond("вопрос", deadline=start + 1)
        self.assertLess(time.monotonic() - start, 0.2)
        self.assertEqual(reply["target_seconds"], 0)

    def test_schedule_subtracts_processing_time(self):
        runtime = Runtime("unused", worker=good_worker)
        entry = {"question": "q", "reply": dict(good_worker("", {}, "", 0),
                 status="ok", target_seconds=20, duplicate=False), "start": 100, "delivered": False}
        runtime._requests["q"] = entry
        with patch("arena.runtime.time.monotonic", return_value=112), patch("arena.runtime.time.sleep") as sleeper:
            runtime.respond("q", request_id="q")
        sleeper.assert_called_once_with(8)


if __name__ == "__main__":
    unittest.main()
