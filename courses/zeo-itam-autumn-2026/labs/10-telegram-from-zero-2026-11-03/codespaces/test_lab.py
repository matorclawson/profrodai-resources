"""Offline tests: a small fake of three Telegram methods stands in for Telegram. Run: python3 -m unittest test_lab"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))


class Fake:
    def __init__(self):
        self.updates, self.sent, self.fail_next, self.next_id = [], [], [], 100
        self.lock = threading.Lock()

    def push(self, text, user=5001, chat=5001):
        with self.lock:
            self.next_id += 1
            self.updates.append({"update_id": self.next_id, "message": {
                "chat": {"id": chat, "type": "private"}, "from": {"id": user}, "text": text}})


def make_server(fake):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            params = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            method = self.path.rsplit("/", 1)[-1]
            if method == "getMe":
                return self.reply(200, {"ok": True, "result": {"username": "LucyShop_bot"}})
            if method == "sendMessage":
                fake.sent.append((params["chat_id"], params["text"]))
                return self.reply(200, {"ok": True, "result": {"message_id": len(fake.sent)}})
            if method == "getUpdates":
                if fake.fail_next:
                    return self.reply(fake.fail_next.pop(0), {"ok": False})
                offset, deadline = params.get("offset"), time.time() + min(params.get("timeout", 0), 1)
                while True:
                    with fake.lock:
                        if offset is not None:
                            fake.updates = [u for u in fake.updates if u["update_id"] >= offset]
                        found = list(fake.updates)
                    if found or time.time() >= deadline:
                        return self.reply(200, {"ok": True, "result": found})
                    time.sleep(0.02)
            self.reply(404, {"ok": False})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class LabTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.server = make_server(self.fake)
        self.dir = tempfile.mkdtemp()
        self.env = dict(os.environ, TELEGRAM_BOT_TOKEN="123:FAKE", PYTHONPATH=HERE,
                        TELEGRAM_API_BASE=f"http://127.0.0.1:{self.server.server_address[1]}")
        os.environ.update(TELEGRAM_BOT_TOKEN="123:FAKE", TELEGRAM_API_BASE=self.env["TELEGRAM_API_BASE"])
        self.old = os.getcwd()
        os.chdir(self.dir)
        for name in ("tg", "bot", "shop"):
            sys.modules.pop(name, None)
        sys.path.insert(0, HERE)
        global tg, bot, shop
        import tg, bot, shop  # noqa: E401

    def tearDown(self):
        os.chdir(self.old)
        self.server.shutdown()
        sys.path.remove(HERE)

    def run_step(self, name, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, name), *args], cwd=self.dir, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_step06_verifies_the_bot(self):
        self.assertIn("Verified @LucyShop_bot", self.run_step("step06_getme.py", "LucyShop_bot").stdout)
        self.assertIn("different bots", self.run_step("step06_getme.py", "other_bot").stderr)

    def test_step07_accepts_hello_lucy_with_extra_characters_and_marks_it_read(self):
        self.fake.push("Hello Lucy!")
        out = self.run_step("step07_read.py")
        self.assertIn("Received: Hello Lucy!", out.stdout)
        with open(os.path.join(self.dir, "offset.txt")) as handle:
            self.assertEqual(handle.read(), "102")

    def test_step07_without_a_message_says_what_to_do(self):
        self.assertIn("Send it to this bot", self.run_step("step07_read.py").stderr)

    def test_step08_sends_to_the_chat_found_in_step07(self):
        self.fake.push("hello lucy", chat=777)
        self.run_step("step07_read.py")
        self.assertIn("accepted message", self.run_step("step08_send.py").stdout)
        self.assertEqual(self.fake.sent, [(777, "Hello from Lucy’s shop!")])

    def test_step08_before_step07_says_so(self):
        self.assertIn("Run step07_read.py first", self.run_step("step08_send.py").stderr)

    def test_hello_is_not_answered_as_a_command_in_step10(self):
        self.fake.push("hello lucy")
        self.run_step("step07_read.py")
        self.fake.push("/stock vanilla")
        self.run_step("step10_answer_once.py")
        self.assertEqual([text for _, text in self.fake.sent], ["vanilla: 2 tubs"])

    def test_step10_does_not_answer_twice(self):
        self.fake.push("/stock chocolate")
        self.run_step("step10_answer_once.py")
        self.run_step("step10_answer_once.py")
        self.assertEqual([text for _, text in self.fake.sent], ["chocolate: 12 tubs"])

    def test_shelf_answers(self):
        self.assertEqual(shop.stock_reply("strawberry"), "strawberry: 0 tubs")
        self.assertEqual(shop.stock_reply("mango"), "Unknown flavor")
        self.assertEqual(shop.answer(1, "/stock Vanilla"), "vanilla: 2 tubs")
        self.assertEqual(shop.answer(1, "hi"), "Try /stock vanilla")

    def test_owner_gets_a_proposal_and_customer_does_not(self):
        self.assertEqual(shop.answer(42, "/restock vanilla", owner_id=42), "Propose 6 tubs")
        self.assertEqual(shop.answer(43, "/restock vanilla", owner_id=42), "Owner only")
        self.assertEqual(shop.answer(42, "/restock vanilla", owner_id=None), "Owner only")
        self.assertEqual(shop.answer(42, "/restock mango", owner_id=42), "No target for that flavor")
        self.assertEqual(shop.STOCK["vanilla"], 2)

    def test_whoami_returns_the_sender_number(self):
        self.assertEqual(shop.answer(98765, "/whoami"), "98765")

    def serve_in_thread(self, owner=None):
        stop, out = threading.Event(), io.StringIO()

        def work():
            with redirect_stdout(out):
                bot.serve(owner, stop=stop, poll_seconds=1, wait=lambda s: time.sleep(0.05))
        thread = threading.Thread(target=work)
        thread.start()
        return stop, thread, out

    def wait_for(self, count, seconds=6):
        end = time.time() + seconds
        while len(self.fake.sent) < count and time.time() < end:
            time.sleep(0.05)

    def test_bot_survives_a_server_error_and_says_so(self):
        stop, thread, out = self.serve_in_thread()
        self.fake.fail_next.append(502)
        time.sleep(0.3)
        self.fake.push("/stock mango")
        self.wait_for(1)
        stop.set()
        thread.join(10)
        self.assertEqual([text for _, text in self.fake.sent], ["Unknown flavor"])
        self.assertIn("Problem: Telegram answered with an error (HTTP 502)", out.getvalue())

    def test_bot_explains_a_409_and_keeps_going(self):
        stop, thread, out = self.serve_in_thread()
        self.fake.fail_next.append(409)
        time.sleep(0.3)
        self.fake.push("/stock vanilla")
        self.wait_for(1)
        stop.set()
        thread.join(10)
        self.assertIn("another program is reading this bot's messages (409)", out.getvalue())
        self.assertEqual(len(self.fake.sent), 1)

    def test_bot_stops_on_a_rejected_token(self):
        self.fake.fail_next.append(401)
        out = io.StringIO()
        with redirect_stdout(out):
            bot.serve(None, poll_seconds=1, wait=lambda s: None)
        self.assertIn("rejected the token (401)", out.getvalue())
        self.assertIn("Stopping.", out.getvalue())

    def test_log_names_the_role_not_the_number_and_never_the_token(self):
        stop, thread, out = self.serve_in_thread(owner=5001)
        self.fake.push("/restock vanilla", user=5001)
        self.fake.push("/restock vanilla", user=6002)
        self.wait_for(2)
        stop.set()
        thread.join(10)
        text = out.getvalue()
        self.assertEqual([t for _, t in self.fake.sent], ["Propose 6 tubs", "Owner only"])
        self.assertIn("owner asked '/restock vanilla'", text)
        self.assertIn("customer asked '/restock vanilla'", text)
        for secret in ("123:FAKE", "5001", "6002"):
            self.assertNotIn(secret, text)

    def test_missing_token_says_how_to_add_one(self):
        env = {k: v for k, v in self.env.items() if k != "TELEGRAM_BOT_TOKEN"}
        result = subprocess.run([sys.executable, os.path.join(HERE, "step06_getme.py"), "x_bot"], cwd=self.dir,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertIn("TELEGRAM_BOT_TOKEN Codespaces secret", result.stderr)


if __name__ == "__main__":
    unittest.main()
