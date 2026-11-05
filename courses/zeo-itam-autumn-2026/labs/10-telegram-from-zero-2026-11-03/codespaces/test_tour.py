"""Offline tests for tour.py: buttons, commands, polls, location and the picture, on a fake Telegram. No network, no keys.
Run: python3 -m unittest test_tour"""
import struct
import unittest
import zlib

import tour

OWNER, FRIEND, STRANGER = 1001, 2002, 3003
ROWS = [{"sku": "VAN", "name": "Vanilla", "on_hand": 12, "reorder_point": 5},
        {"sku": "CHO", "name": "Chocolate", "on_hand": 3, "reorder_point": 5}]


class FakeInner:
    """Stands in for the messenger underneath: hands out the queued updates and records what the agent would see."""
    account = "1234"

    def __init__(self):
        self.updates, self.asked = [], []

    def call(self, method, data):
        self.asked.append((method, data))
        given, self.updates = list(self.updates), []  # Telegram forgets what the cursor has passed
        return given


class TourTests(unittest.TestCase):
    def setUp(self):
        self.inner, self.calls, self.uploads, self.sleeps = FakeInner(), [], [], []
        self.api_error = None

        def api(method, **params):
            if self.api_error:
                raise self.api_error
            self.calls.append((method, params))
            if method == "sendMessage":
                return {"message_id": 70 + len(self.calls)}
            if method == "getMe":
                return {"username": "LucyShop_bot"}
            return True

        self.tour = tour.Tour(self.inner, api, lambda method, fields, *rest: self.uploads.append((method, fields, rest)),
                              owner_id=OWNER, known=lambda: {FRIEND}, stock=lambda: ROWS,
                              shop={"lat": 19.4326, "lon": -99.1332}, pause=self.sleeps.append)
        self.calls.clear()

    def push(self, update_id, **kind):
        self.inner.updates.append(dict(update_id=update_id, **kind))

    def message(self, user, text=None, chat_type="private", **extra):
        message = {"from": {"id": user, "is_bot": False}, "chat": {"id": user if chat_type == "private" else -500, "type": chat_type}}
        if text is not None:
            message["text"] = text
        message.update(extra)
        return message

    def names(self):
        return [name for name, _ in self.calls]

    def test_menu_command_sends_an_inline_keyboard_and_hides_the_update_from_the_agent(self):
        self.push(1, message=self.message(FRIEND, "/menu"))
        seen = self.tour.call("getUpdates", {"offset": 0})
        self.assertEqual(seen, [{"update_id": 1}])  # consumed, but the cursor can still move past it
        method, params = self.calls[0]
        self.assertEqual(method, "sendMessage")
        self.assertIn("inline_keyboard", params["reply_markup"])

    def test_ordinary_text_still_reaches_the_agent_untouched(self):
        self.push(2, message=self.message(FRIEND, "do you have vanilla?"))
        self.assertEqual(self.tour.call("getUpdates", {})[0]["message"]["text"], "do you have vanilla?")
        self.assertEqual(self.calls, [])

    def test_getupdates_asks_for_the_extra_kinds_but_the_agent_asked_for_less(self):
        self.tour.call("getUpdates", {"offset": 7, "allowed_updates": ["message"]})
        self.assertEqual(self.inner.asked[0][1]["allowed_updates"], tour.UPDATE_KINDS)
        self.assertEqual(self.inner.asked[0][1]["offset"], 7)

    def test_a_button_edits_the_same_message_and_stops_the_spinner(self):
        self.push(3, callback_query={"id": "q1", "from": {"id": FRIEND}, "data": "flavors",
                                     "message": {"message_id": 9, "chat": {"id": FRIEND}}})
        self.assertEqual(self.tour.call("getUpdates", {}), [{"update_id": 3}])
        self.assertEqual(self.names(), ["answerCallbackQuery", "editMessageText"])
        edit = self.calls[1][1]
        self.assertEqual(edit["message_id"], 9)
        self.assertIn("Vanilla: 12", edit["text"])
        self.assertIn("Chocolate: 3", edit["text"])

    def test_the_restock_button_is_owner_only_by_sender_id_not_by_button_data(self):
        for user, who in ((FRIEND, "friend"), (OWNER, "owner")):
            self.calls.clear()
            self.push(4, callback_query={"id": "q", "from": {"id": user}, "data": "restock",
                                         "message": {"message_id": 9, "chat": {"id": user}}})
            self.tour.call("getUpdates", {})
            if who == "friend":
                self.assertEqual(self.names(), ["answerCallbackQuery"])
                self.assertTrue(self.calls[0][1]["show_alert"])
            else:
                self.assertEqual(self.names(), ["answerCallbackQuery", "editMessageText"])

    def test_a_stranger_is_ignored_everywhere(self):
        self.push(5, message=self.message(STRANGER, "/menu"))
        self.push(6, callback_query={"id": "q", "from": {"id": STRANGER}, "data": "flavors", "message": {"message_id": 1, "chat": {"id": STRANGER}}})
        self.push(7, poll_answer={"poll_id": "p", "user": {"id": STRANGER}, "option_ids": [0]})
        seen = self.tour.call("getUpdates", {})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.tour.votes, {})
        self.assertEqual(seen[1:], [{"update_id": 6}, {"update_id": 7}])  # the strangers' buttons and votes never reach the agent

    def test_vote_command_builds_a_poll_from_the_real_product_list(self):
        self.push(8, message=self.message(OWNER, "/vote"))
        self.tour.call("getUpdates", {})
        method, params = self.calls[0]
        self.assertEqual((method, params["options"], params["is_anonymous"]), ("sendPoll", ["Vanilla", "Chocolate"], False))

    def test_poll_answers_are_counted_for_known_people_only(self):
        self.push(9, poll_answer={"poll_id": "p", "user": {"id": FRIEND}, "option_ids": [1]})
        self.tour.call("getUpdates", {})
        self.assertEqual(self.tour.votes, {"p": 1})

    def test_where_asks_for_location_and_a_shared_location_gets_a_distance(self):
        self.push(10, message=self.message(FRIEND, "/where"))
        self.tour.call("getUpdates", {})
        self.assertTrue(self.calls[0][1]["reply_markup"]["keyboard"][0][0]["request_location"])
        self.calls.clear()
        self.push(11, message=self.message(FRIEND, location={"latitude": 19.4326, "longitude": -99.2332}))
        self.assertEqual(self.tour.call("getUpdates", {})[-1], {"update_id": 11})
        self.assertIn("10.5 km", self.calls[0][1]["text"])  # 0.1 degree of longitude at this latitude
        self.assertEqual(self.calls[0][1]["reply_markup"], {"remove_keyboard": True})

    def test_progress_edits_one_message_three_times_in_place(self):
        self.push(12, message=self.message(FRIEND, "/progress"))
        self.tour.call("getUpdates", {})
        self.assertEqual(self.names(), ["sendMessage", "editMessageText", "editMessageText"])
        self.assertEqual({params["message_id"] for name, params in self.calls[1:]}, {self.calls[0][1].get("message_id", 71)})
        self.assertEqual(self.sleeps, [1.0, 1.0])

    def test_card_uploads_a_valid_png_drawn_from_the_stock_rows(self):
        self.push(13, message=self.message(FRIEND, "/card"))
        self.tour.call("getUpdates", {})
        method, fields, rest = self.uploads[0]
        png = rest[2]
        self.assertEqual((method, rest[0], rest[1]), ("sendPhoto", "photo", "stock.png"))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (360, 2 * 36 + 10))
        idat = png[png.index(b"IDAT") + 4:png.rindex(b"IEND") - 8]
        self.assertEqual(len(zlib.decompress(idat)), height * (1 + width * 3))

    def test_in_a_group_only_menu_for_this_bot_is_answered(self):
        self.push(14, message=self.message(FRIEND, "/menu@LucyShop_bot", chat_type="supergroup"))
        self.push(15, message=self.message(FRIEND, "/menu@OtherBot", chat_type="supergroup"))
        self.push(16, message=self.message(FRIEND, "/vote", chat_type="supergroup"))
        self.tour.call("getUpdates", {})
        self.assertEqual(self.names(), ["getMe", "sendMessage"])
        self.assertEqual(self.calls[1][1]["chat_id"], -500)

    def test_a_telegram_failure_is_swallowed_and_the_cursor_still_moves(self):
        self.push(17, message=self.message(FRIEND, "/menu"))
        self.api_error = OSError("down")
        self.assertEqual(self.tour.call("getUpdates", {}), [{"update_id": 17}])

    def test_the_command_menu_is_registered_once_and_a_failure_does_not_stop_the_shop(self):
        calls = []
        tour.Tour(FakeInner(), lambda method, **params: calls.append(method), None, owner_id=OWNER, known=set, stock=list, shop={})
        self.assertEqual(calls, ["setMyCommands"])

        def broken(method, **params):
            raise OSError("no")

        tour.Tour(FakeInner(), broken, None, owner_id=OWNER, known=set, stock=list, shop={})  # must not raise

    def test_other_methods_pass_straight_through(self):
        self.assertEqual(self.tour.call("sendMessage", {"chat_id": 1, "text": "x"}), [])
        self.assertEqual(self.inner.asked[-1], ("sendMessage", {"chat_id": 1, "text": "x"}))


if __name__ == "__main__":
    unittest.main()
