#!/usr/bin/env bash
# Trains the agent and opens Mantle's Inspector on port 5010. Prints no key.
set -eu
cd "$(dirname "$0")"
for name in RASA_LICENSE OPENAI_API_KEY DEEPGRAM_API_KEY; do
  [ -n "${!name:-}" ] || { echo "Missing Codespaces secret: $name"; exit 1; }
done
python3 -m unittest test_shop || { echo "The shelf tests failed. Fix them before training."; exit 1; }
RASA="${RASA_BIN:-$HOME/.venv-mantle/bin/rasa}"
"$RASA" train
exec "$RASA" inspect --port 5010
