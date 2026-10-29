"""Plug the Agents API session into the book's channel loop.

The book's `serve` polls, claims work, runs one turn through `run_claim`, then delivers the report. Its
`run_claim` drives a local model over the shop tools. Here we replace only that one step: the turn goes to
the conversation's hosted Agents API session instead. Queue, leases, reports and "unknown is never resent"
stay exactly as in Chapter 9.
"""


import logging

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())
HOLD = "I have asked the owner and will come back to you."
REFUSE = "I can only help with this shop's orders and questions."


def make_run_claim(agent, decide=None):
    """`decide(text)` returns answer, ask_owner or refuse (see decision.py); None means always answer."""
    def run_claim(db, queue, assignment, model):
        try:
            label = decide(assignment.text) if decide else "answer"
            if label == "answer":
                answer = agent.reply(assignment.session_id, assignment.text)
            else:
                answer = HOLD if label == "ask_owner" else REFUSE
            passed = label == "answer" and bool(answer)
        except Exception as error:  # a failed turn still ends, with a plain apology, so the queue never sticks
            answer, passed = "I could not answer that just now. Please send it again.", False
            log.warning("agent turn failed: %s", type(error).__name__)
        queue.finish(assignment, answer or "I have nothing to add.")
        return passed, None

    return run_claim


def install(channel, agent, decide=None):
    """Make the book's serve() use our turn. `channel` is the dict from runpy of the ch09 file."""
    namespace = channel["serve"].__globals__
    original = namespace["run_claim"]
    namespace["run_claim"] = make_run_claim(agent, decide)
    return original  # tests put it back with namespace["run_claim"] = original
