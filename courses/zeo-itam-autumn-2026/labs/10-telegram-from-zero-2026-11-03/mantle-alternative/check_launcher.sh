#!/usr/bin/env bash
# Offline check that run.sh stops when a shelf test fails. Uses dummy values, no network, no paid call.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp "$here/run.sh" "$here/shop.py" "$here/test_shop.py" "$tmp/"
sed -i.bak 's/"Propose 6 tubs"/"Propose 5 tubs"/' "$tmp/test_shop.py"
marker="$tmp/rasa-was-called"
printf '#!/bin/sh\ntouch "%s"\n' "$marker" > "$tmp/fake-rasa"
chmod +x "$tmp/fake-rasa"
RASA_LICENSE=x OPENAI_API_KEY=x DEEPGRAM_API_KEY=x RASA_BIN="$tmp/fake-rasa" bash "$tmp/run.sh" >/dev/null 2>&1
status=$?
if [ "$status" -ne 0 ] && [ ! -e "$marker" ]; then echo "PASS: run.sh refused after a failing test (exit $status) and never started rasa"; exit 0; fi
echo "FAIL: exit $status, rasa called: $([ -e "$marker" ] && echo yes || echo no)"; exit 1
