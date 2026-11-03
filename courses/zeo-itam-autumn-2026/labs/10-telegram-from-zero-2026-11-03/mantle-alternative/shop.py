"""Lucy's shelf and the two answers. No Rasa code here, so the tests run anywhere.

INVENTORY is the shelf. Change a number, restart the agent, ask again.
"""
import os

INVENTORY = {"vanilla": 2, "chocolate": 12, "strawberry": 0}
TARGET = 8


def stock_reply(item):
    item = (item or "").lower().strip()
    if item in INVENTORY:
        return f"{item}: {INVENTORY[item]} tubs"
    return "Unknown flavor"


def is_owner(sender_id):
    """Lucy is whoever the LUCY_SENDER_ID setting names. If it is not set, nobody is Lucy."""
    owner = os.environ.get("LUCY_SENDER_ID", "").strip()
    return bool(owner) and str(sender_id) == owner


def restock_reply(sender_id, item):
    item = (item or "").lower().strip()
    if not is_owner(sender_id):
        return "Owner only"
    if item != "vanilla":
        return "No target for that flavor"
    return f"Propose {max(0, TARGET - INVENTORY[item])} tubs"
