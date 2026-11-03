"""Lucy's shop bot, running in the foreground. Every message and every problem is printed here.

  python3 step10_answer_once.py          answer what is waiting, then stop (step 10)
  python3 bot.py                         keep answering until you press Ctrl+C (steps 11 to 15)
  python3 bot.py --owner 123456789       same, and the number 123456789 may use /restock (steps 12 and 13)

Ctrl+C is how you stop it. A problem with the connection is printed and retried; it does not end the bot.
"""
import argparse
import time

import shop
from tg import TelegramError, api, private_texts

OFFSET_FILE = "offset.txt"


def stamp():
    return time.strftime("%H:%M:%S")


def read_offset():
    try:
        with open(OFFSET_FILE) as handle:
            return int(handle.read())
    except (OSError, ValueError):
        return None


def save_offset(value):
    with open(OFFSET_FILE, "w") as handle:
        handle.write(str(value))


def handle_waiting(owner_id=None, poll_seconds=2):
    """Read what is waiting, answer each text, remember how far we got. Returns the count answered."""
    offset = read_offset()
    params = {"timeout": poll_seconds}
    if offset is not None:
        params["offset"] = offset
    answered = 0
    for update in api("getUpdates", **params):
        for message in private_texts([update]):
            sender = message["from"]["id"]
            reply = shop.answer(sender, message["text"], owner_id)
            api("sendMessage", chat_id=message["chat"]["id"], text=reply)
            role = "owner" if owner_id is not None and sender == owner_id else "customer"
            print(f"[{stamp()}] {role} asked {message['text']!r}, answered {reply!r}", flush=True)
            answered += 1
        save_offset(update["update_id"] + 1)
    return answered


def serve(owner_id=None, stop=None, poll_seconds=20, wait=time.sleep):
    """Keep answering. stop is an optional threading.Event, used by the tests."""
    print(f"[{stamp()}] Listening. Send /stock vanilla to your bot. Press Ctrl+C to stop.", flush=True)
    pause = 2
    while not (stop and stop.is_set()):
        try:
            handle_waiting(owner_id, poll_seconds)
            pause = 2
        except TelegramError as error:
            if error.code == 401:
                print(f"[{stamp()}] {error} Stopping.", flush=True)
                return
            print(f"[{stamp()}] Problem: {error} Trying again in {pause} seconds.", flush=True)
            wait(pause)
            pause = min(pause * 2, 30)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner", type=int, default=None, help="the number from your own /whoami reply")
    args = parser.parse_args()
    try:
        serve(args.owner)
    except KeyboardInterrupt:
        print(f"\n[{stamp()}] Stopped. New messages now wait until you start bot.py again.", flush=True)


if __name__ == "__main__":
    main()
