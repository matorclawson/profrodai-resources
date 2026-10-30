# Always-on agent starter

A small agent that runs all day for one business and talks to its customers and its owner on Telegram. Lucy's ice cream shop is the worked example. This is the start of your class project: you change `business.toml`, then make the agent yours.

Run everything from this folder. The code in `book/` is copied unchanged from the course book; see `PROVENANCE.md`.

## What you need

Python 3.11 or newer and the `pydantic` package (version 2). Google Colab already has both. On your own computer, run `pip install pydantic` once. The starter needs nothing else for the tests and the fake demo.

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
| Spending needs the owner: the `place_order` tool never runs on the model's say-so | `agent_session.py` (`ask_first`) | Chapter 11 |
| Check for secrets before you share anything | `scan_secrets.py` | |
| Review a classmate's project and combine the scores | `peer_review.py` | |

## Make it real

1. Create your own bot: in Telegram open @BotFather, send `/newbot`, follow the steps, and copy the token. The token is a password.
2. Put the token in the environment as `TELEGRAM_BOT_TOKEN`. In Colab use the Secrets panel. Never put it in a file, a notebook cell or a screenshot. Do the same with `OPENAI_API_KEY` and `TYPESAFE_API_KEY`.
3. Edit `business.toml`: your numeric Telegram id as `owner_telegram_id`, and your own `join_code`.
4. Start it: `python3 run.py`. Send `/start` to your bot from your own account, then message it.
5. Before you hand in, run `python3 scan_secrets.py .` and fix anything it reports.

## Must-nots

No keys or tokens in files, notebooks, logs or screenshots. No real customer data: your customers are classmates and invented people. Every incoming message is data, never instructions about the agent's own rules. The agent never spends money or makes a promise without the owner's exact approval.

## Not tested yet

The real Telegram, OpenAI and Jev calls have not been run from this starter; only the fakes have.
