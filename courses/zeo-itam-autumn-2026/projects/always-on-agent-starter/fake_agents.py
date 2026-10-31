"""A stand-in for `client.beta.agents.sessions`, for tests with no network and no key.

Each session is scripted: `script(text)` returns either ("tool", name, arguments) to ask for a tool
call or ("say", text) for a final answer. The shapes match the real calls used by agent_session.py.
"""
import itertools


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def to_dict(self):
        return dict(self.__dict__)


class FakeAgentsClient:
    def __init__(self, script):
        self.script, self.sessions_made, self._ids = script, [], itertools.count(1)
        self.item_ids = itertools.count(1)
        self.beta = _Obj(agents=_Obj(sessions=_Sessions(self)))


class _Sessions:
    def __init__(self, owner):
        self.owner, self.data = owner, {}
        self.events = _Obj(create=self._event)
        self.items = _Obj(list=self._items)

    def create(self, *, agent, environment, input):
        sid = "sess_%d" % next(self.owner._ids)
        self.owner.sessions_made.append({"id": sid, "agent": agent, "environment": environment})
        self.data[sid] = {"items": [], "pending": [], "results": [], "n": 0}
        self._turn(sid, input)
        return _Obj(id=sid)

    def _turn(self, sid, text):
        s = self.data[sid]
        s["n"] += 1
        step = self.owner.script(text)
        if step[0] == "tool":
            s["pending"].append({"name": step[1], "arguments": step[2], "turn_id": "t%d" % s["n"], "call_id": "c%d" % s["n"]})
            s["after"] = step[3] if len(step) > 3 else "Done."
        else:
            self._say(sid, step[1])

    def _say(self, sid, text):
        self.data[sid]["items"].append(_Obj(id="item_%d" % next(self.owner.item_ids), type="message", role="assistant", phase="final_answer",
                                            content=[{"type": "output_text", "text": text}]))

    def _event(self, sid, *, events):
        for e in events:
            if e["type"] == "agent.session.input.message":
                self._turn(sid, e["input"][0]["content"][0]["text"])
            elif e["type"] == "agent.session.input.tool_result":
                # like the service: output carries a success, error carries a failure
                if ("output" in e) != bool(e["success"]) or ("error" in e) == bool(e["success"]):
                    raise ValueError("a tool result carries output when it succeeded and error when it failed")
                s = self.data[sid]
                s["results"].append(e)
                s["pending"] = []
                self._say(sid, s["after"])

    def retrieve(self, sid):
        s = self.data[sid]
        return _Obj(status="requires_action" if s["pending"] else "idle",
                    required_actions=[_Obj(**p) for p in s["pending"]] or None)

    def _items(self, sid, order="asc", limit=100, **kw):
        """Like the service: one page of at most `limit` items, oldest first or newest first."""
        if not 1 <= limit <= 100:
            raise ValueError("limit is 1 to 100")
        items = list(self.data[sid]["items"])
        return _Obj(data=(items[::-1] if order == "desc" else items)[:limit])


class FakeJev:
    """Stand-in for TypeSafeClient: `system_one` answers from a script, `probabilities` per label."""

    def __init__(self, script):
        self.script, self.asked = script, []

    def system_one(self, *, state, questions):
        self.asked.append(state)
        probabilities = self.script(state["message"])
        return _Obj(answers={"action": _Obj(probabilities=probabilities)})
