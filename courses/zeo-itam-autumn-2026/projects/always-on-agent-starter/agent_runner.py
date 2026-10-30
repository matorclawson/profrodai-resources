"""Plug the Agents API session into the book's channel loop.

The book's `serve` polls, claims work, runs one turn through `run_claim`, then delivers the report. Its
`run_claim` drives a local model over the shop tools. Here we replace only that one step: the turn goes to
the conversation's hosted Agents API session instead. Queue, leases, reports and "unknown is never resent"
stay exactly as in Chapter 9.

When Jev says a message needs the owner, a second piece of work is put on the same durable queue, routed to the
owner's chat, so the owner really receives it through the same inbox and outbox rules (once, never resent after
an unknown delivery). If the owner cannot be reached, the customer is told so instead of being told the owner knows.
"""


import logging

import schedule_daily

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())
HOLD = "I have passed this to the owner."
NO_OWNER = "I could not reach the owner right now. Please try again later."
ESCALATION_SESSION = "owner-escalations"
REFUSE = "I can only help with this shop's orders and questions."


def escalate(db, queue, assignment, owner_route):
    """Put one message for the owner on the queue. True when it is stored (also when it was stored before)."""
    if not owner_route:
        return False
    customer = assignment.session_id.rsplit(":", 1)[-1]
    text = "A customer needs you. Customer %s wrote: %s" % (customer, assignment.text[:300].replace("\n", " "))
    with db.immediate() as connection:
        work = schedule_daily.WAKE["admit"](connection, queue, "escalation:%d" % assignment.work_id, ESCALATION_SESSION, text, owner_route)
    return work is not None


def make_run_claim(agent, decide=None, owner_route=None):
    """`decide(text)` returns answer, ask_owner or refuse (see decision.py); None means always answer.
    `owner_route` is (channel, owner chat id as text); None means the owner cannot be reached."""
    def run_claim(db, queue, assignment, model):
        if assignment.session_id == ESCALATION_SESSION:  # made by this file, never by a customer: send the text as it is
            queue.finish(assignment, assignment.text)
            return True, None
        try:
            label = decide(assignment.text) if decide else "answer"
            if label == "answer":
                answer = agent.reply(assignment.session_id, assignment.text)
            elif label == "ask_owner":
                answer = HOLD if escalate(db, queue, assignment, owner_route) else NO_OWNER
            else:
                answer = REFUSE
            passed = label == "answer" and bool(answer)
        except Exception as error:  # a failed turn still ends, with a plain apology, so the queue never sticks
            answer, passed = "I could not answer that just now. Please send it again.", False
            log.warning("agent turn failed: %s", type(error).__name__)
        queue.finish(assignment, answer or "I have nothing to add.")
        return passed, None

    return run_claim


def install(channel, agent, decide=None, owner_route=None):
    """Make the book's serve() use our turn. `channel` is the dict from runpy of the ch09 file."""
    namespace = channel["serve"].__globals__
    original = namespace["run_claim"]
    namespace["run_claim"] = make_run_claim(agent, decide, owner_route)
    return original  # tests put it back with namespace["run_claim"] = original
