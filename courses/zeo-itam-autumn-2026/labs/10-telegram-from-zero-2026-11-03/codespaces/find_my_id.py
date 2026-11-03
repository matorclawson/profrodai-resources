"""Step 07: read the first message sent to your bot and learn who sent it. Send your bot any message first."""
import json
import re
from pathlib import Path

from tg import TelegramError, api, private_texts

try:
    batch = api("getUpdates", timeout=3)
except TelegramError as error:
    raise SystemExit(str(error))
messages = list(private_texts(batch))
if not messages:
    raise SystemExit("No message found yet. Send any message to your bot, then run this again.")
mine = messages[-1]["from"]["id"]
print("Received:", messages[-1]["text"][:40])
print("The number Telegram gives you (your owner id):", mine)
config = Path("business.toml")
text = config.read_text()
updated = re.sub(r"^owner_telegram_id = \d+", f"owner_telegram_id = {mine}", text, count=1, flags=re.M)
if updated != text:
    config.write_text(updated)
    print("Saved it in business.toml as owner_telegram_id.")
else:
    print("business.toml already holds an owner id; change it by hand if you want a different one.")
print("Hide this number when you share your screen.")
