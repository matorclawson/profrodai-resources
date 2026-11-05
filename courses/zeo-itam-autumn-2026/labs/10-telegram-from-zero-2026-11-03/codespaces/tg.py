"""The one function every step uses to talk to Telegram. Standard library only.

The token comes from the TELEGRAM_BOT_TOKEN setting and is never printed.
TELEGRAM_API_BASE exists only so the offline tests can point this at a local fake.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")


class TelegramError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def token():
    value = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if ":" not in value:
        sys.exit("No bot token found. Add the TELEGRAM_BOT_TOKEN Codespaces secret, "
                 "or run: source set_token.sh")
    return value


def api(method, **params):
    request = urllib.request.Request(
        f"{BASE}/bot{token()}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise TelegramError("Telegram rejected the token (401). Copy it again from BotFather.", 401) from None
        if exc.code == 409:
            raise TelegramError("Telegram says another program is reading this bot's messages (409). "
                                "Stop the other bot.py, or use a fresh bot.", 409) from None
        raise TelegramError(f"Telegram answered with an error (HTTP {exc.code}).", exc.code) from None
    except (OSError, ValueError):
        raise TelegramError("The request to Telegram failed. Check the connection.") from None
    if not result.get("ok"):
        raise TelegramError("Telegram refused the request.")
    return result["result"]


def api_upload(method, fields, file_field, filename, content, content_type="image/png"):
    """A Bot API call that carries a file (sendPhoto, sendDocument). Plain multipart/form-data, standard library only."""
    boundary = "----lucy" + os.urandom(8).hex()
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(f"{BASE}/bot{token()}/{method}", data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.load(response)
    except (OSError, ValueError):
        raise TelegramError("The upload to Telegram failed. Check the connection.") from None
    if not result.get("ok"):
        raise TelegramError("Telegram refused the upload.")
    return result["result"]


def private_texts(updates):
    """Yield the text messages sent to the bot in a private chat."""
    for update in updates:
        message = update.get("message", {})
        if message.get("chat", {}).get("type") == "private" and "text" in message:
            yield message
