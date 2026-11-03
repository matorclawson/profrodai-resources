# Lucy's shop on Rasa Mantle (the same class, without Telegram)

## Why this version exists

The class is about one idea: a shop assistant that tells everyone how many tubs are on the shelf, but lets only the owner ask for a restock. The Telegram notebook teaches it with a phone and a bot token. This version teaches the same sequence with Rasa Mantle, where the agent runs in a Codespace and you talk to it in the Inspector, by typing or by voice. Pick the one that fits your day. Nothing here changes the Telegram notebook.

## The sequence you will see

1. Ask "How many vanilla tubs does Lucy have?" The answer is 2.
2. Change one number in the shelf (`INVENTORY` in `shop.py`), restart, ask again. The answer is 7. Ask: where did that number come from?
3. Ask about strawberry (an empty shelf: 0 tubs) and mango (not sold: unknown flavor). Two different answers.
4. With 2 tubs and a target of 8, Lucy asks for a restock and gets "Propose 6 tubs". A customer asking the same thing gets "Owner only".
5. The proposal changes nothing on the shelf. Ask for the stock again to prove it.

## What you need

- A GitHub account that can open a Codespace.
- Three keys, added as Codespaces secrets in your own GitHub settings and made available to this repository: `RASA_LICENSE`, `OPENAI_API_KEY` and `DEEPGRAM_API_KEY`. They are never written into any file here.
- The shop owner's sender setting, `LUCY_SENDER_ID` (see "Who is Lucy").

## Open it

[Open in a Codespace](https://codespaces.new/profrodai/profrodai-resources?devcontainer_path=.devcontainer/itam-lucy-mantle/devcontainer.json)

When it is ready, open a terminal and run `bash run.sh`. It runs the offline tests, trains the agent and starts the Inspector on port 5010.

## Who is Lucy

The agent does not believe anyone who types "I am Lucy". The restock tool reads who is asking from the channel, a field the person cannot type, and compares it with `LUCY_SENDER_ID`. If that setting is empty, nobody is Lucy and everyone gets "Owner only".

## The files

- `shop.py`: the shelf and the two answers. Plain Python, no Rasa.
- `test_shop.py`: eight offline tests of the sequence above. Run `python3 -m unittest test_shop`.
- `agent.yml`, `integrations.yml`: the agent, the model and the voice settings.
- `skills/check_stock`, `skills/propose_restock`: one skill each, with the tool the agent may call.

## For the instructor

- Show the Telegram notebook, this version, or both. The sequence and the numbers match.
- Tests passing offline says nothing about the agent in a Codespace. State which of the following has been observed before class: Codespace opens, `run.sh` trains, Inspector answers by text, Inspector answers by voice, owner and customer get different replies.
- Voice uses the browser microphone. If it fails, the text chat still teaches the whole sequence.
