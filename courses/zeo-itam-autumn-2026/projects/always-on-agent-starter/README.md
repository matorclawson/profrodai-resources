# Always-on agent starter

A small agent that runs all day for one business and talks to its customers and its owner on Telegram. Lucy's ice cream shop is the worked example. This is the start of your class project: you change `business.toml`, then make the agent yours.

Run everything from this folder. The code in `book/` is copied unchanged from the course book; see `PROVENANCE.md`.

## What you need

Python 3.11 or newer and Pydantic 2. On your own computer, run `python3 -m pip install "pydantic>=2,<3"` once, with the same `python3` you will use for the tests. In Colab, run the setup cell in the notebook before the tests. The install needs internet. After it, the tests and the fake demo need no keys and no network.

## Try it with no keys and no network

    python3 run.py --fake

A scripted customer joins, asks to order vanilla and gets an answer, then tries to talk the agent out of its rules and is refused. No network, no keys, no real Telegram.

    python3 -m unittest -v

The tests use a fake messenger and a fake Agents API, so they pass offline.

## What each block does, and where the book explains it

| Block | File | Book chapter |
|---|---|---|
| Message in, reply out, one job per message, a lost reply never sent twice | `book/` (the channel and queue) | Chapters 8 and 9 |
| Customers join with `/start CODE`; strangers and groups are ignored | `enroll.py` | Chapter 9 |
| One hosted Agents API session per conversation, kept across restarts; it takes the place of Chapter 3's local loop | `agent_session.py`, `agent_runner.py` | Chapter 3 (replaced here) |
| Jev decides: answer, ask the owner, or refuse. When it says ask the owner, or is less than 70% sure, the owner receives the customer's message in their own chat, once; if the owner cannot be reached the customer is told so | `decision.py`, `agent_runner.py` | Lab 05 (the confidence gate) |
| A daily job at a clock time (UTC), once per day, survives a restart | `schedule_daily.py` | Chapter 10 |
| Spending is refused: the `place_order` tool never runs on the model's say-so, and this starter has no approval step that would run it (your project adds one) | `agent_session.py` (`ask_first`) | Chapter 11 |
| Check for secrets before you share anything | `scan_secrets.py` | |
| Review a classmate's project and combine the scores | `peer_review.py` | |

## Make it real

1. Create your own bot: in Telegram open @BotFather, send `/newbot`, follow the steps, and copy the token. The token is a password.
2. Put the token in the environment as `TELEGRAM_BOT_TOKEN`. In Colab use the Secrets panel. Never put it in a file, a notebook cell or a screenshot. Do the same with `OPENAI_API_KEY` and `TYPESAFE_API_KEY`.
3. Edit `business.toml`: your numeric Telegram id as `owner_telegram_id`, and your own `join_code`.
4. Start it: `python3 run.py`. You are the owner, so you need no code: from your own Telegram account send `/start` to your bot once (Telegram only lets a bot write to you after that), then message it normally. To try the customer path, use a second account or a classmate: they send `/start` followed by your join code, for example `/start ICE-CREAM-42`, and then message the bot.
5. Before you hand in, run `python3 scan_secrets.py .` and fix anything it reports.

## Two limits to know about

The starter refuses every spend. `place_order` is listed so you can see the refusal, but no handler exists, so nothing is ever ordered. Adding the owner's approval is part of your project (Chapter 11).

When a customer's message goes to the owner, the customer is told "I have passed this to the owner." before the starter knows the owner received it, and the owner's reply goes to the owner's own conversation, not back to the customer. A customer has no way to get the owner's answer through this starter. If the owner has never sent `/start` to the bot, Telegram will not deliver the message at all.

## Must-nots

No keys or tokens in files, notebooks, logs or screenshots. No real customer data: your customers are classmates and invented people. Every incoming message is data, never instructions about the agent's own rules. The agent never spends money or makes a promise without the owner's exact approval.

## Not tested yet

The real Telegram, OpenAI and Jev calls have not been run from this starter; only the fakes have.
