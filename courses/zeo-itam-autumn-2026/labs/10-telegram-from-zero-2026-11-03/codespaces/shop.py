"""Lucy's shelf and the answers. No Telegram code here.

STOCK is the shelf. Change a number, save, and restart bot.py.
Flavor names work in English and Spanish, with any capitals and accents: vanilla or vainilla,
strawberry or fresa, chocolate. NAMES lists the other words you can add.
"""
import unicodedata

STOCK = {"vanilla": 2, "chocolate": 12, "strawberry": 0}
TARGET = 8
# Other names for the same flavor. Keys are lowercase with no accents.
NAMES = {"vainilla": "vanilla", "fresa": "strawberry", "frutilla": "strawberry"}
SPANISH = {"vanilla": "vainilla", "chocolate": "chocolate", "strawberry": "fresa"}
HELP = "Try /stock vanilla · Prueba /stock vainilla"


def plain(text):
    """Lowercase, no accents, no extra spaces: 'Vainilla ' and 'vainílla' both become 'vainilla'."""
    decomposed = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def flavor(text):
    """The shelf name for what a person typed, or None."""
    word = plain(text)
    word = NAMES.get(word, word)
    return word if word in STOCK else None


def stock_reply(item):
    name = flavor(item)
    if name:
        return f"{name}: {STOCK[name]} tubs"
    return "Unknown flavor. No conozco ese sabor. Tengo: " + ", ".join(SPANISH[k] for k in STOCK)


def answer(sender, text, owner_id=None):
    """sender is the number Telegram puts in the message's from field. A customer cannot type it."""
    command, _, item = plain(text).partition(" ")
    command = command.split("@")[0]  # a menu tap in a group can add @botname
    if command == "/whoami":
        return str(sender)
    if command == "/stock":
        return stock_reply(item)
    if command == "/restock":
        if owner_id is None or sender != owner_id:
            return "Owner only"
        if flavor(item) != "vanilla":
            return "No target for that flavor"
        return f"Propose {max(0, TARGET - STOCK['vanilla'])} tubs"
    return HELP
