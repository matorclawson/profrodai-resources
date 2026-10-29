"""A fake messenger for tests with no network: the same two operations the Telegram class offers.

The book's channel code only needs an object with `.account` and `.call(method, data)`. This one
holds the updates a customer would send, records every message the agent sends, and can lose a
reply on purpose (the message is delivered, then the call raises) so a test can check that a lost
reply is never sent twice.
"""


class FakeMessenger:
    def __init__(self, account="1234"):
        self.account = account
        self.updates = []          # what Telegram would hand to getUpdates
        self.sent = []             # every message the agent really sent
        self.lose_next_reply = False
        self._next_message_id = 1

    def push(self, user_id, text, *, update_id=None, chat_type="private"):
        """A customer message arrives. Pass the same update_id twice to model a redelivery."""
        if update_id is None:
            update_id = len(self.updates) + 1
        self.updates.append(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "from": {"id": user_id, "is_bot": False},
                    "chat": {"id": user_id, "type": chat_type},
                    "text": text,
                },
            }
        )

    def call(self, method, data):
        if method == "getUpdates":
            offset = data.get("offset", 0)
            return [u for u in self.updates if u["update_id"] >= offset][:100]
        if method == "sendMessage":
            self.sent.append({"chat_id": data["chat_id"], "text": data["text"]})
            if self.lose_next_reply:
                self.lose_next_reply = False
                raise OSError("reply lost after the message was delivered")
            message_id, self._next_message_id = self._next_message_id, self._next_message_id + 1
            return {"message_id": message_id}
        raise ValueError("unsupported operation")
