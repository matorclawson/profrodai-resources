"""Hand a Telegram message to a Rasa agent and bring its answer back. Standard library only.
The Rasa agent runs separately (`rasa run --enable-api --interface 127.0.0.1 --port 5005` in the Rasa folder) and its REST channel
listens at /webhooks/rest/webhook. Nothing needs a public address: this program calls it on localhost and sends the answer with sendMessage.
"""
import json
import os
import urllib.error
import urllib.request

RASA_URL = os.environ.get("RASA_URL", "").rstrip("/")   # for example http://127.0.0.1:5005


class RasaError(RuntimeError):
    pass


def ask_rasa(chat_id, text, base=None, token=None):
    """Send one message as this Telegram chat and return the list of reply texts (an empty list if Rasa says nothing)."""
    base = (base or RASA_URL).rstrip("/")
    if not base:
        raise RasaError("RASA_URL is not set.")
    url = base + "/webhooks/rest/webhook" + (f"?token={token}" if token else "")
    request = urllib.request.Request(url, data=json.dumps({"sender": str(chat_id), "message": text}).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            replies = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        raise RasaError("Rasa did not answer. Is `rasa run --enable-api` running on the address in RASA_URL?") from None
    return [r["text"] for r in replies if isinstance(r, dict) and r.get("text")]
