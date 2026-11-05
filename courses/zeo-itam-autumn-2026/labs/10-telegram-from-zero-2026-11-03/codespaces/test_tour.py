"""Offline tests for tour.py: a recording stand-in replaces Telegram. Run: python3 -m unittest test_tour"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["TOUR_OWNER_ID"] = "1001"
import tour  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, method, **params):
        self.calls.append((method, params))
        return {"message_id": 7, "url": "", "can_read_all_group_messages": False, "username": "t"}

    def methods(self):
        return [m for m, _ in self.calls]


def msg(text, user=2002, kind="private", **extra):
    return {"message": {"chat": {"id": user, "type": kind}, "from": {"id": user}, "text": text, **extra}}


class TourTests(unittest.TestCase):
    def run_update(self, update):
        rec = Recorder()
        tour.handle(rec, update, sleep=lambda s: None)
        return rec

    def test_start_sets_the_command_menu(self):
        rec = self.run_update(msg("/start"))
        self.assertEqual(rec.methods(), ["setMyCommands", "sendMessage"])
        self.assertEqual(len(rec.calls[0][1]["commands"]), len(tour.COMMANDS))

    def test_buttons_send_an_inline_keyboard(self):
        rec = self.run_update(msg("/buttons"))
        keyboard = rec.calls[0][1]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([b["callback_data"] for b in keyboard], ["flavor:vanilla", "flavor:strawberry"])

    def test_a_button_press_is_answered_and_the_message_is_edited(self):
        rec = self.run_update({"callback_query": {"id": "q1", "from": {"id": 2002}, "data": "flavor:vanilla",
                                                  "message": {"message_id": 9, "chat": {"id": 2002}}}})
        self.assertEqual(rec.methods(), ["answerCallbackQuery", "editMessageText"])
        self.assertEqual(rec.calls[1][1]["text"], "You picked vanilla.")

    def test_only_the_owner_can_approve(self):
        def press(user):
            return self.run_update({"callback_query": {"id": "q2", "from": {"id": user}, "data": "restock:yes",
                                                        "message": {"message_id": 9, "chat": {"id": 2002}}}})
        stranger, owner = press(2002), press(1001)
        self.assertEqual(stranger.methods(), ["answerCallbackQuery"])
        self.assertTrue(stranger.calls[0][1]["show_alert"])
        self.assertEqual(owner.methods(), ["answerCallbackQuery", "editMessageText"])
        self.assertIn("nothing was ordered", owner.calls[1][1]["text"])

    def test_progress_edits_one_message_three_times(self):
        rec = self.run_update(msg("/progress"))
        self.assertEqual(rec.methods(), ["sendMessage", "sendChatAction", "editMessageText"] * 1 + ["sendChatAction", "editMessageText", "sendChatAction", "editMessageText"])
        self.assertEqual({p["message_id"] for m, p in rec.calls if m == "editMessageText"}, {7})
        self.assertTrue(rec.calls[-1][1]["text"].startswith("Done."))

    def test_poll_and_photo_and_location_button(self):
        self.assertEqual(self.run_update(msg("/poll")).calls[0][0], "sendPoll")
        self.assertEqual(self.run_update(msg("/photo")).calls[0][0], "sendPhoto")
        keyboard = self.run_update(msg("/where")).calls[0][1]["reply_markup"]["keyboard"][0][0]
        self.assertTrue(keyboard["request_location"])

    def test_a_shared_location_is_acknowledged_without_echoing_it(self):
        rec = self.run_update(msg("", location={"latitude": 51.5, "longitude": -0.12}))
        self.assertNotIn("51.5", rec.calls[0][1]["text"])
        self.assertEqual(rec.calls[0][1]["reply_markup"], {"remove_keyboard": True})

    def test_webhook_and_group_report_what_telegram_says(self):
        self.assertIn("polling", self.run_update(msg("/webhook")).calls[1][1]["text"])
        group = self.run_update(msg("/group@LucyShop_bot", kind="supergroup"))
        self.assertIn("supergroup", group.calls[1][1]["text"])

    def test_unknown_commands_and_plain_text(self):
        self.assertIn("do not know", self.run_update(msg("/nope")).calls[0][1]["text"])
        self.assertEqual(self.run_update(msg("hello")).calls, [])


if __name__ == "__main__":
    unittest.main()
