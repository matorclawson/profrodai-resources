"""Lucy's shelf and the answers. No Telegram code here.

STOCK is the shelf. Change a number, save, and restart bot.py.
"""
STOCK = {"vanilla": 2, "chocolate": 12, "strawberry": 0}
TARGET = 8


def stock_reply(item):
    item = (item or "").lower().strip()
    if item in STOCK:
        return f"{item}: {STOCK[item]} tubs"
    return "Unknown flavor"


def answer(sender, text, owner_id=None):
    """sender is the number Telegram puts in the message's from field. A customer cannot type it."""
    command, _, item = (text or "").lower().strip().partition(" ")
    item = item.strip()
    if command == "/whoami":
        return str(sender)
    if command == "/stock":
        return stock_reply(item)
    if command == "/restock":
        if owner_id is None or sender != owner_id:
            return "Owner only"
        if item != "vanilla":
            return "No target for that flavor"
        return f"Propose {max(0, TARGET - STOCK[item])} tubs"
    return "Try /stock vanilla"
