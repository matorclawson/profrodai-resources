#!/usr/bin/env bash
# Trains the agent and opens Mantle's Inspector on port 5010. Prints no key.
set -eu
cd "$(dirname "$0")"
for name in RASA_LICENSE OPENAI_API_KEY DEEPGRAM_API_KEY; do
  [ -n "${!name:-}" ] || { echo "Missing Codespaces secret: $name"; exit 1; }
done
python3 -I -m unittest test_shop 2>&1 | tail -3
"$HOME/.venv-mantle/bin/rasa" train
exec "$HOME/.venv-mantle/bin/rasa" inspect --port 5010
