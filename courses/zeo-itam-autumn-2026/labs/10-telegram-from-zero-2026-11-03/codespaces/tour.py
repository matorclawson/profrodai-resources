"""A tour of what the Telegram Bot API can do beyond plain text, one feature per command.
Standard library only. Run:  python3 tour.py          (needs TELEGRAM_BOT_TOKEN, see README)
Offline tests:               python3 -m unittest test_tour

/commands  the command menu     /buttons  inline keyboard and a callback     /approve  owner-only buttons
/progress  one message edited in place     /poll  a poll     /where  location button     /photo  a picture
/webhook   polling or webhook?   /group  what a bot sees in a group
"""
import os
import time

from tg import TelegramError, api

OWNER_ID = int(os.environ.get("TOUR_OWNER_ID", "0") or 0)   # Telegram id of the owner; find_my_id.py prints yours
PHOTO = "https://telegram.org/img/t_logo.png"
COMMANDS = [("buttons", "Inline buttons and callbacks"), ("approve", "Owner-only approval buttons"),
            ("progress", "Edit one message to show progress"), ("poll", "Send a poll"),
            ("where", "Ask for a location"), ("photo", "Send a picture"),
            ("webhook", "Polling or webhook?"), ("group", "What a bot sees in a group")]
ALLOWED = ["message", "callback_query", "poll_answer"]


def say(call, chat, text, **extra):
    return call("sendMessage", chat_id=chat, text=text, **extra)


def on_command(call, message, sleep=time.sleep):
    chat, user = message["chat"]["id"], message.get("from", {}).get("id")
    word = message["text"].split()[0].split("@")[0].lower()
    if word in ("/start", "/commands"):
        call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
        say(call, chat, "Type / to see the command menu. Each command shows one thing the Bot API can do.")
    elif word == "/buttons":
        say(call, chat, "Which flavor?", reply_markup={"inline_keyboard": [[
            {"text": "Vanilla", "callback_data": "flavor:vanilla"}, {"text": "Strawberry", "callback_data": "flavor:strawberry"}]]})
    elif word == "/approve":
        say(call, chat, "Restock proposal: 6 tubs of vanilla. Owner only.", reply_markup={"inline_keyboard": [[
            {"text": "Approve", "callback_data": "restock:yes"}, {"text": "Reject", "callback_data": "restock:no"}]]})
    elif word == "/progress":
        sent = say(call, chat, "Working. Step 0 of 3")
        for step in (1, 2, 3):
            call("sendChatAction", chat_id=chat, action="typing")
            sleep(1)
            call("editMessageText", chat_id=chat, message_id=sent["message_id"],
                 text=f"Working. Step {step} of 3" if step < 3 else "Done. Three steps, one message.")
    elif word == "/poll":
        call("sendPoll", chat_id=chat, question="Which flavor should Lucy restock first?",
             options=["Vanilla", "Strawberry", "Mango"], is_anonymous=False)
    elif word == "/where":
        say(call, chat, "Tap the button to share where you are. Telegram asks you first.", reply_markup={
            "keyboard": [[{"text": "Share my location", "request_location": True}]], "one_time_keyboard": True, "resize_keyboard": True})
    elif word == "/photo":
        call("sendPhoto", chat_id=chat, photo=PHOTO, caption="A photo sent by URL. Telegram fetches it.")
    elif word == "/webhook":
        info = call("getWebhookInfo")
        mode = "a webhook is set: " + info["url"] if info.get("url") else "polling (no webhook set)"
        say(call, chat, f"This bot uses {mode}. Polling asks Telegram for news. A webhook makes Telegram call your public https address.")
    elif word == "/group":
        me = call("getMe")
        kind = message["chat"].get("type", "private")
        say(call, chat, f"Chat type: {kind}. Can read all group messages: {me.get('can_read_all_group_messages')}. "
                        "By default a bot in a group sees only commands, replies to it and mentions.")
    else:
        say(call, chat, "I do not know that command. Type / to see the menu.")


def on_callback(call, query):
    chat, message_id = query["message"]["chat"]["id"], query["message"]["message_id"]
    kind, _, value = query["data"].partition(":")
    if kind == "restock" and query["from"]["id"] != OWNER_ID:
        return call("answerCallbackQuery", callback_query_id=query["id"], text="Owner only.", show_alert=True)
    call("answerCallbackQuery", callback_query_id=query["id"])
    text = {"flavor": f"You picked {value}.", "restock": "Approved: nothing was ordered, this is a demo." if value == "yes" else "Rejected."}.get(kind, "Done.")
    call("editMessageText", chat_id=chat, message_id=message_id, text=text)


def handle(call, update, sleep=time.sleep):
    if "callback_query" in update:
        on_callback(call, update["callback_query"])
    elif "poll_answer" in update:
        pass   # a vote arrives as its own update, with the option numbers chosen
    elif "message" in update:
        message = update["message"]
        if message.get("text", "").startswith("/"):
            on_command(call, message, sleep)
        elif "location" in message:
            say(call, message["chat"]["id"], "Got a location. The bot receives latitude and longitude; this demo does not store them.",
                reply_markup={"remove_keyboard": True})


def main():
    me = api("getMe")
    print(f"Tour bot @{me['username']} is listening. Press Ctrl+C to stop.")
    api("deleteWebhook")   # polling and a webhook cannot both be on
    api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
    offset = None
    try:
        while True:
            for update in api("getUpdates", offset=offset, timeout=30, allowed_updates=ALLOWED):
                offset = update["update_id"] + 1
                try:
                    handle(api, update)
                except TelegramError as error:
                    print("Telegram refused one request:", error)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
