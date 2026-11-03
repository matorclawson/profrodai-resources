"""Step 10: answer whatever is waiting, once, then stop. Send /stock vanilla to your bot first."""
import bot
from tg import TelegramError

try:
    count = bot.handle_waiting()
except TelegramError as error:
    raise SystemExit(str(error))
print("Checked waiting messages. Answered", count, "- look in your shop chat.")
