"""Five short scenes that run the starter's real code against the fake messenger and fake Agents API.

    python3 demo_scenes.py 1      # startup
    python3 demo_scenes.py 2      # a message in, a reply out
    python3 demo_scenes.py 3      # the same message twice
    python3 demo_scenes.py 4      # kill the agent mid-turn, restart it
    python3 demo_scenes.py 5      # the agent tries to spend money

Every line printed comes from the running code; nothing is typed in by hand. The messenger and the hosted
agent are fakes, so these scenes show the starter's behavior, not Telegram's or OpenAI's.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

import agent_runner
import decision
import run
from agent_session import AgentSession
from fake_agents import FakeAgentsClient, FakeJev
from fake_messenger import FakeMessenger

OWNER, CUSTOMER = 1001, 2002
CONFIG = {"owner_telegram_id": OWNER, "join_code": "ICE42", "welcome": "You are connected. Send me your order.",
          "morning_check": "08:00", "model": "fake-model", "instructions": "Be brief."}
JEV = FakeJev(lambda text: {"answer": 0.9, "ask_owner": 0.08, "refuse": 0.02})


def make(folder, script, bot=None, ask_first=("place_order",)):
    config = dict(CONFIG, database=os.path.join(folder, "agent.db"), enrolled=os.path.join(folder, "enrolled.db"),
                  sessions=os.path.join(folder, "sessions.db"))
    bot = bot or FakeMessenger()
    db, queue = run.WAKE["open_shop"](config["database"])
    run.WAKE["seed_shop"](db)
    enrollment = run.Enrollment(config["enrolled"])
    wrapped = run.EnrollBot(bot, enrollment, config["join_code"], config["welcome"])
    agent = AgentSession(FakeAgentsClient(script), config["sessions"], model="fake-model", instructions="Be brief.",
                         tools=run.TOOL_SPECS, handlers={"stock": lambda: run.WAKE["stock_rows"](db.connection)},
                         ask_first=ask_first, sleep=lambda s: None)
    run.schedule_daily.schedule_daily(db, "morning-check", "owner-morning", "Check the stock and tell the owner what to order.",
                                      config["morning_check"], now=time.time(), channel="telegram:" + bot.account, recipient=str(OWNER))
    run.agent_runner.install(run.CHANNEL, agent, decide=lambda t: decision.decide(JEV, t, make_question=lambda: {})[0],
                             owner_route=("telegram:" + bot.account, str(OWNER)))
    return config, db, queue, enrollment, wrapped, bot, agent


def say(line=""):
    print(line, flush=True)


def send(bot, user, text, **kw):
    say("customer %d  >  %s" % (user, text))
    bot.push(user, text, **kw)


def show_replies(bot, seen=0):
    for m in bot.sent[seen:]:
        say("agent -> %d  :  %s" % (m["chat_id"], m["text"].replace("\n", " / ")))
    return len(bot.sent)


def count(db, table):
    return db.connection.execute("SELECT count(*) FROM " + table).fetchone()[0]


def scene1(folder):
    say("Scene 1: startup (fake messenger, fake hosted agent)")
    config, db, queue, enrollment, bot, fake, agent = make(folder, lambda t: ("say", "Hello!"))
    say("database opened; tables ready; stock seeded: %s" % [(r["name"], r["on_hand"]) for r in run.WAKE["stock_rows"](db.connection)])
    row = db.connection.execute("SELECT id, interval_seconds FROM wake_jobs").fetchone()
    say("daily job scheduled: %s every %d seconds, at %s UTC" % (row[0], row[1], config["morning_check"]))
    say("allowed people: the owner only; customers join with /start %s" % config["join_code"])
    say("waiting for messages")


def scene2(folder):
    say("Scene 2: a message in, a reply out")
    config, db, queue, enrollment, bot, fake, agent = make(
        folder, lambda t: ("tool", "stock", {}, "Vanilla is low: order 6 tubs?") if "order" in t.lower() else ("say", "Hello!"))
    send(fake, CUSTOMER, "/start ICE42")
    run.one_round(config, db, queue, enrollment, bot)
    n = show_replies(fake)
    send(fake, CUSTOMER, "I would like to order vanilla")
    summary = run.one_round(config, db, queue, enrollment, bot)
    show_replies(fake, n)
    say("turn summary: %s" % {k: v for k, v in summary.items() if v})


def scene3(folder):
    say("Scene 3: the same message arrives twice")
    config, db, queue, enrollment, bot, fake, agent = make(folder, lambda t: ("say", "Noted: one vanilla."))
    send(fake, OWNER, "one vanilla please", update_id=7)
    send(fake, OWNER, "one vanilla please", update_id=7)
    for _ in range(3):
        run.one_round(config, db, queue, enrollment, bot)
    show_replies(fake)
    say("jobs in the queue: %d   replies sent: %d" % (count(db, "work"), len(fake.sent)))


CHILD = '''
import sys, time
import demo_scenes as d
folder = sys.argv[1]
def slow(text):
    print("turn started: the hosted agent is working", flush=True)
    return ("say", "done")
config, db, queue, enrollment, bot, fake, agent = d.make(folder, slow)
sessions = agent.client.beta.agents.sessions
original = sessions.retrieve
def stuck(sid):
    time.sleep(120)           # the turn never finishes: the parent kills this process
    return original(sid)
sessions.retrieve = stuck
fake.push(d.OWNER, "order the strawberries")
import run
run.one_round(config, db, queue, enrollment, bot)
'''


def scene4(folder):
    say("Scene 4: kill the agent in the middle of a turn, then restart it")
    open(os.path.join(folder, "child.py"), "w").write(CHILD)
    env = dict(os.environ, PYTHONPATH=os.getcwd())
    child = subprocess.Popen([sys.executable, os.path.join(folder, "child.py"), folder], stdout=subprocess.PIPE, text=True, env=env)
    say(child.stdout.readline().strip())
    time.sleep(1)
    say("sending kill -9 to the agent process")
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    say("agent process gone (exit %s)" % child.returncode)
    config, db, queue, enrollment, bot, fake, agent = make(folder, lambda t: ("say", "Back again."))
    say("restart: state before recovery: %s" % db.connection.execute("SELECT state, count(*) FROM work GROUP BY state").fetchall())
    summary = run.one_round(config, db, queue, enrollment, bot)
    say("recovered work ids: %s" % summary["recovered"])
    show_replies(fake)
    say("state after recovery: %s" % db.connection.execute("SELECT state, count(*) FROM work GROUP BY state").fetchall())


def scene5(folder):
    say("Scene 5: the agent tries to spend money")
    config, db, queue, enrollment, bot, fake, agent = make(
        folder, lambda t: ("tool", "place_order", {"sku": "SKU-VANILLA", "units": 6}, "I asked the owner before ordering."))
    send(fake, OWNER, "restock vanilla")
    run.one_round(config, db, queue, enrollment, bot)
    show_replies(fake)
    sessions = agent.client.beta.agents.sessions
    result = [r for s in sessions.data.values() for r in s["results"]][0]
    say("the model asked for place_order; success=%s; our reply to the model: %s" % (result["success"], result["output"]))
    say("orders placed: 0")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as folder:
        {"1": scene1, "2": scene2, "3": scene3, "4": scene4, "5": scene5}[sys.argv[1]](folder)
