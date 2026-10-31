"""A daily job at a clock time, on Chapter 10's durable scheduler.

Chapter 10 runs jobs on a fixed interval. A shop wants "every morning at 08:00", so this file works out the
first 08:00 and hands the book a 24 hour interval. Times are UTC on purpose: a 24 hour interval would drift
by an hour across a daylight saving change, so the starter does not pretend to local time. The book's own
rules do the rest: the due time is stored in SQLite, a restart does not repeat or lose a run, and several
missed days become one run rather than a backlog.
"""
import datetime
import runpy

WAKE = runpy.run_path("book/textbook/learner/profrod_sovereign_agent_ch10_wakeups_learner.py")
DAY = 86_400


def next_daily_utc(now, hhmm):
    """The first UTC epoch at or after `now` that falls on hh:mm."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("hh:mm between 00:00 and 23:59 required")
    moment = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    first = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if first.timestamp() < now:
        first += datetime.timedelta(days=1)
    return first.timestamp()


def schedule_daily(db, identifier, session, prompt, hhmm, *, now, channel="local", recipient=""):
    """Add the job once; a second call with the same identifier leaves the stored job alone."""
    try:
        WAKE["schedule"](db, identifier, session, prompt, first_due=next_daily_utc(now, hhmm),
                         interval_seconds=DAY, channel=channel, recipient=recipient)
        return True
    except ValueError as error:
        if "already exists" not in str(error):
            raise
        return False
