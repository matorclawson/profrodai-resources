"""Offline tests for rasa_bridge.py and its use in tour.py: a small fake of Rasa's REST channel stands in for Rasa.
Run: python3 -m unittest test_rasa_bridge"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["TOUR_OWNER_ID"] = "1001"
import rasa_bridge  # noqa: E402
import tour  # noqa: E402

SEEN = []


class FakeRasa(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append((self.path, body))
        replies = [{"recipient_id": body["sender"], "text": "Propose 6 tubs"}, {"recipient_id": body["sender"], "image": "x.png"},
                   {"recipient_id": body["sender"], "text": "Owner only"}]
        data = json.dumps(replies).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRasa)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_a_message_goes_out_as_the_chat_and_only_text_replies_come_back(self):
        SEEN.clear()
        self.assertEqual(rasa_bridge.ask_rasa(2002, "restock vanilla", base=self.base), ["Propose 6 tubs", "Owner only"])
        self.assertEqual(SEEN[0], ("/webhooks/rest/webhook", {"sender": "2002", "message": "restock vanilla"}))

    def test_no_rasa_means_a_clear_error_not_a_crash_in_the_bot(self):
        with self.assertRaises(rasa_bridge.RasaError):
            rasa_bridge.ask_rasa(1, "hi", base="http://127.0.0.1:9")
        with self.assertRaises(rasa_bridge.RasaError):
            rasa_bridge.ask_rasa(1, "hi", base="")

    def test_the_tour_bot_hands_plain_text_to_rasa_when_it_is_plugged_in(self):
        calls = []
        tour.handle(lambda m, **p: calls.append((m, p)) or {"message_id": 1}, {"message": {"chat": {"id": 2002, "type": "private"}, "from": {"id": 2002}, "text": "restock vanilla"}},
                    sleep=lambda s: None, rasa=lambda chat, text: rasa_bridge.ask_rasa(chat, text, base=self.base))
        self.assertEqual([p["text"] for m, p in calls if m == "sendMessage"], ["Propose 6 tubs", "Owner only"])

    def test_if_rasa_is_down_the_user_is_told_and_the_bot_keeps_running(self):
        calls = []
        def down(chat, text):
            raise rasa_bridge.RasaError("Rasa did not answer.")
        tour.handle(lambda m, **p: calls.append((m, p)) or {"message_id": 1}, {"message": {"chat": {"id": 2002, "type": "private"}, "from": {"id": 2002}, "text": "hello"}},
                    sleep=lambda s: None, rasa=down)
        self.assertIn("could not reach", calls[0][1]["text"])


if __name__ == "__main__":
    unittest.main()
