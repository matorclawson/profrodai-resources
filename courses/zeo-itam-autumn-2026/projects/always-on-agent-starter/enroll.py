"""Customer enrolment: who may talk to the agent besides its owner.

The book's channel code answers only an explicit allowlist. This file keeps that allowlist in a small
SQLite table and lets a customer join by sending `/start CODE` to the bot. The join message is
consumed here, so the book's code never sees it and the agent never treats it as an order.
The owner can remove a customer; a removed customer is a stranger again.
"""
import sqlite3


class Enrollment:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS customers (user_id INTEGER PRIMARY KEY)")
        self.connection.commit()

    def customers(self):
        return frozenset(row[0] for row in self.connection.execute("SELECT user_id FROM customers"))

    def enroll(self, user_id):
        """True only the first time, so a repeated join message gets no second welcome."""
        with self.connection:
            cursor = self.connection.execute("INSERT OR IGNORE INTO customers VALUES (?)", (user_id,))
        return cursor.rowcount == 1

    def remove(self, user_id):
        with self.connection:
            self.connection.execute("DELETE FROM customers WHERE user_id = ?", (user_id,))

    def close(self):
        self.connection.close()


class EnrollBot:
    """Wraps a messenger. `/start CODE` in a private chat from a person enrols them and is dropped."""

    def __init__(self, bot, enrollment, code, welcome="You are connected. Send me your order."):
        self.bot, self.enrollment, self.code, self.welcome = bot, enrollment, code, welcome

    @property
    def account(self):
        return self.bot.account

    def call(self, method, data):
        result = self.bot.call(method, data)
        if method != "getUpdates":
            return result
        kept = []
        for update in result:
            if self._join(update.get("message")):
                # Keep the id, drop the content: the channel code then moves its cursor past the join message.
                if type(update.get("update_id")) is int and update["update_id"] >= 0:
                    kept.append({"update_id": update["update_id"]})
                continue
            kept.append(update)
        return kept

    def _join(self, message):
        """True when the message was a join attempt (right code or wrong), so it is not passed on."""
        if not isinstance(message, dict):
            return False
        text, sender, chat = message.get("text"), message.get("from"), message.get("chat")
        if not (isinstance(text, str) and isinstance(sender, dict) and isinstance(chat, dict)):
            return False
        words = text.split()
        if not words or words[0] != "/start":
            return False
        user = sender.get("id")
        if (
            type(user) is int
            and user > 0
            and chat.get("type") == "private"
            and chat.get("id") == user
            and not sender.get("is_bot")
            and words[1:] == [self.code]
            and self.enrollment.enroll(user)
        ):
            self.bot.call("sendMessage", {"chat_id": user, "text": self.welcome})
        return True
