"""Look for secrets in a folder before you share it. Rubric line 7.

    python3 scan_secrets.py [folder]        exit code 0 = nothing found, 1 = something found

It reads text files and notebooks (cell sources and outputs) and reports file and line, never the secret
itself. It finds the common shapes only: a Telegram bot token, an `sk-` style API key, and a name like
api_key, token, secret or password assigned a long quoted value. A clean scan is evidence, not proof.
"""
import json
import pathlib
import re
import sys

PATTERNS = {
    "telegram bot token": re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),
    "api key (sk-)": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "assigned secret": re.compile(r"""(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['"][A-Za-z0-9_\-./+=]{16,}['"]"""),
}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT = {".py", ".md", ".txt", ".toml", ".json", ".cfg", ".env", ".yml", ".yaml", ".ipynb", ".sh", ""}


def lines_of(path):
    text = path.read_text(errors="replace")
    if path.suffix == ".ipynb":
        try:
            for cell in json.loads(text).get("cells", []):
                yield "".join(cell.get("source", []))
                for out in cell.get("outputs", []):
                    body = out.get("text") or out.get("data", {}).get("text/plain") or ""
                    yield "".join(body) if isinstance(body, list) else str(body)
            return
        except ValueError:
            pass
    yield text


def scan(folder):
    found = []
    for path in sorted(pathlib.Path(folder).rglob("*")):
        if not path.is_file() or path.suffix not in TEXT or SKIP_DIRS & set(path.parts):
            continue
        for block in lines_of(path):
            for number, line in enumerate(block.splitlines(), 1):
                for name, pattern in PATTERNS.items():
                    if pattern.search(line):
                        found.append((str(path), number, name))
    return found


if __name__ == "__main__":
    hits = scan(sys.argv[1] if len(sys.argv) > 1 else ".")
    for path, number, name in hits:
        print("%s:%d: looks like a %s (value not shown)" % (path, number, name))
    print("secrets scan: %s" % ("FOUND %d" % len(hits) if hits else "nothing found"))
    sys.exit(1 if hits else 0)
