"""Step 09: the shelf, with no Telegram involved."""
from shop import STOCK, stock_reply

for item in ("vanilla", "chocolate", "strawberry", "mango", "Vainilla"):
    print(stock_reply(item))
