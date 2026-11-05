"""What the Telegram Bot API can do besides text, in Lucy's own bot (lab 10, class 5 Nov).

Lucy's agent reads only text messages. This wrapper sits between Telegram and that agent and answers the other
things people can do in a chat: press an inline button, pick a command, answer a poll, share a location, ask for a
picture. It never reaches the model. Each handled update is replaced by its bare update id, so the agent's cursor
still moves past it and nothing is read twice.

  /menu      inline keyboard: buttons send a callback query; the same message is edited in place
  /vote      a poll built from the shop's real product list
  /where     a keyboard button that asks for the sender's location, then the distance to the shop
  /card      a picture the program draws from the stock table and uploads
  /progress  one message edited three times, the way a long job shows progress

Who may press what is decided by the sender id Telegram attaches to the update, never by the button's own data,
because anyone can forge the data string. Only the owner and enrolled customers are served.
"""
import logging
import math
import struct
import zlib

log = logging.getLogger("lucy.tour")
COMMANDS = [
    {"command": "menu", "description": "Buttons: flavors, hours, restock"},
    {"command": "vote", "description": "Vote for the next flavor"},
    {"command": "where", "description": "How far is the shop from you"},
    {"command": "card", "description": "A picture of today's stock"},
    {"command": "progress", "description": "Watch one message update itself"},
]
UPDATE_KINDS = ["message", "callback_query", "poll_answer"]
OWNER_ONLY = "Owner only. Solo la dueña o el dueño."


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def stock_card_png(rows, width=360, bar_height=26, gap=10):
    """A small PNG bar chart of tubs on hand, drawn with the standard library. Red bars are at or under the reorder point."""
    height = max(1, len(rows)) * (bar_height + gap) + gap
    scale = (width - 2 * gap) / max([row["on_hand"] for row in rows] + [1])
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)  # PNG filter type: none
        index, offset = divmod(y - gap, bar_height + gap)
        row = rows[index] if 0 <= y - gap and index < len(rows) and offset < bar_height else None
        bar = int(row["on_hand"] * scale) if row else 0
        colour = (214, 69, 65) if row and row["on_hand"] <= row["reorder_point"] else (63, 142, 99)
        for x in range(width):
            pixels += bytes(colour if row and gap <= x < gap + bar else (250, 247, 240))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(pixels))) + chunk(b"IEND", b"")


class Tour:
    """The wrapper. `api(method, **params)` makes a Bot API call; `upload` sends a file; both are passed in so tests use fakes."""

    def __init__(self, inner, api, upload, *, owner_id, known, stock, shop, pause=lambda seconds: None):
        self.bot, self.api, self.upload = inner, api, upload
        self.owner_id, self.known, self.stock, self.shop, self.pause = owner_id, known, stock, shop, pause
        self.username = None
        self.votes = {}
        try:
            self.api("setMyCommands", commands=COMMANDS)
        except Exception as error:  # a missing menu must never stop the shop
            log.warning("could not set the command menu (%s)", type(error).__name__)

    @property
    def account(self):
        return self.bot.account

    def call(self, method, data):
        if method != "getUpdates":
            return self.bot.call(method, data)
        updates = self.bot.call(method, dict(data, allowed_updates=UPDATE_KINDS))
        kept = []
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                kept.append(update)
                continue
            if self.handle(update):
                kept.append({"update_id": update["update_id"]})  # consumed: the cursor still moves past it
            elif "message" in update:
                kept.append(update)
            else:
                kept.append({"update_id": update["update_id"]})  # a kind the agent does not read
        return kept

    def handle(self, update):
        """True when this update was one of the tour's. Failures are logged by class name and never reach the agent."""
        try:
            if "callback_query" in update:
                return self.on_callback(update["callback_query"])
            if "poll_answer" in update:
                return self.on_poll_answer(update["poll_answer"])
            if "message" in update:
                return self.on_message(update["message"])
        except Exception as error:
            log.warning("tour update failed (%s)", type(error).__name__)
            return True
        return False

    def allowed(self, user_id):
        return type(user_id) is int and (user_id == self.owner_id or user_id in self.known())

    # ---- messages: commands, location ----
    def on_message(self, message):
        sender, chat = message.get("from") or {}, message.get("chat") or {}
        user, chat_id = sender.get("id"), chat.get("id")
        if sender.get("is_bot") or not self.allowed(user):
            return False
        if isinstance(message.get("location"), dict):
            return self.on_location(chat_id, message["location"])
        words = (message.get("text") or "").split()
        if not words or not words[0].startswith("/"):
            return False
        command, _, target = words[0][1:].partition("@")
        if target and target.lower() != self.me().lower():
            return True  # a command meant for another bot in the same group
        if chat.get("type") != "private" and command != "menu":
            return True  # in groups the tour answers only /menu
        action = {"menu": self.menu, "vote": self.vote, "where": self.where, "card": self.card, "progress": self.progress}.get(command)
        if action is None:
            return False
        action(chat_id)
        return True

    def me(self):
        if self.username is None:
            self.username = self.api("getMe").get("username", "")
        return self.username

    def menu(self, chat_id):
        keyboard = [[{"text": "Sabores / Flavors", "callback_data": "flavors"}, {"text": "Horario / Hours", "callback_data": "hours"}],
                    [{"text": "Reabastecer / Restock (owner)", "callback_data": "restock"}]]
        self.api("sendMessage", chat_id=chat_id, text="Lucy's shop. Press a button. / Toca un botón.", reply_markup={"inline_keyboard": keyboard})

    def vote(self, chat_id):
        names = [row["name"] for row in self.stock()][:10]
        self.api("sendPoll", chat_id=chat_id, question="Next flavor? / ¿Próximo sabor?", options=names, is_anonymous=False)

    def where(self, chat_id):
        button = {"text": "Share my location / Compartir ubicación", "request_location": True}
        self.api("sendMessage", chat_id=chat_id, text="Tap the button and I will tell you how far the shop is.",
                 reply_markup={"keyboard": [[button]], "resize_keyboard": True, "one_time_keyboard": True})

    def card(self, chat_id):
        png = stock_card_png(self.stock())
        self.upload("sendPhoto", {"chat_id": chat_id, "caption": "Tubs on hand. Red is at or under the reorder point."}, "photo", "stock.png", png)

    def progress(self, chat_id):
        sent = self.api("sendMessage", chat_id=chat_id, text="Checking stock… 1/3")
        for step in ("Comparing with the reorder points… 2/3", "Done. 3/3"):
            self.pause(1.0)
            self.api("editMessageText", chat_id=chat_id, message_id=sent["message_id"], text=step)

    def on_location(self, chat_id, location):
        km = distance_km(location["latitude"], location["longitude"], self.shop["lat"], self.shop["lon"])
        self.api("sendMessage", chat_id=chat_id, text="The shop is %.1f km from you. / La tienda está a %.1f km." % (km, km),
                 reply_markup={"remove_keyboard": True})
        return True

    # ---- callback queries: the buttons ----
    def on_callback(self, query):
        user, message = (query.get("from") or {}).get("id"), query.get("message") or {}
        if not self.allowed(user) or "id" not in query:
            return True
        chat_id, message_id, action = (message.get("chat") or {}).get("id"), message.get("message_id"), query.get("data")
        if action == "restock" and user != self.owner_id:  # authority comes from the sender id, not from the button's data
            self.api("answerCallbackQuery", callback_query_id=query["id"], text=OWNER_ONLY, show_alert=True)
            return True
        if action == "flavors":
            lines = ["%s: %d" % (row["name"], row["on_hand"]) for row in self.stock()]
            text, back = "Flavors and tubs:\n" + "\n".join(lines), True
        elif action == "hours":
            text, back = "Open 10:00 to 20:00 every day. / Abierto de 10:00 a 20:00 todos los días.", True
        elif action == "restock":
            text, back = "Tell me in a message, for example: propose 12 tubs of vanilla. I will draft it and ask for your yes.", True
        elif action == "back":
            text, back = "Lucy's shop. Press a button. / Toca un botón.", False
        else:
            self.api("answerCallbackQuery", callback_query_id=query["id"])
            return True
        self.api("answerCallbackQuery", callback_query_id=query["id"], text="Updated")  # stops the button's spinner
        keyboard = [[{"text": "Back / Volver", "callback_data": "back"}]] if back else \
            [[{"text": "Sabores / Flavors", "callback_data": "flavors"}, {"text": "Horario / Hours", "callback_data": "hours"}],
             [{"text": "Reabastecer / Restock (owner)", "callback_data": "restock"}]]
        self.api("editMessageText", chat_id=chat_id, message_id=message_id, text=text, reply_markup={"inline_keyboard": keyboard})
        return True

    # ---- polls ----
    def on_poll_answer(self, answer):
        user = (answer.get("user") or {}).get("id")
        if not self.allowed(user):
            return True
        chosen = answer.get("option_ids") or []
        self.votes[answer.get("poll_id")] = self.votes.get(answer.get("poll_id"), 0) + len(chosen)
        log.info("poll answer: %d option(s) chosen; %d votes so far on this poll", len(chosen), self.votes[answer.get("poll_id")])
        return True
