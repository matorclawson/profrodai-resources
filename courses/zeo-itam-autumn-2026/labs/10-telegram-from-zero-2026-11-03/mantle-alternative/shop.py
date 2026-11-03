"""Lucy's shelf and the two answers. No Rasa code here, so the tests run anywhere.

INVENTORY is the shelf. Change a number, restart the agent, ask again.
"""
import os

INVENTORY = {"vanilla": 2, "chocolate": 12, "strawberry": 0}
TARGET = 8
# Lucy's shop PIN. Change it before class; the LUCY_PIN setting wins if it is set.
OWNER_PIN = "4242"


def stock_reply(item):
    item = (item or "").lower().strip()
    if item in INVENTORY:
        return f"{item}: {INVENTORY[item]} tubs"
    return "Unknown flavor"


def is_owner(pin):
    """Lucy is whoever knows the shop PIN. This teaches the idea of a permission check
    that lives in code, not in the chat. It is not a login: anyone who learns the PIN is Lucy."""
    expected = os.environ.get("LUCY_PIN", "").strip() or OWNER_PIN
    return bool(expected) and str(pin or "").strip() == expected


def restock_reply(pin, item):
    item = (item or "").lower().strip()
    if not is_owner(pin):
        return "Owner only"
    if item != "vanilla":
        return "No target for that flavor"
    return f"Propose {max(0, TARGET - INVENTORY[item])} tubs"
