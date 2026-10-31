"""One OpenAI Agents API session per conversation (the Agents API, not the Agents SDK).

`client` is an `openai.OpenAI(...)` in a real run and `FakeAgentsClient` in tests; both have the same
`client.beta.agents.sessions` surface. A conversation keeps its hosted session across messages, and the
session id is stored in SQLite, so the agent still knows the conversation after a restart.

Tools are plain JSON specs plus our own Python functions. A tool named in `ask_first` never runs on the
model's say-so: it returns a message telling the model to ask the owner. This starter has no approval step
that would run it later, so spending is always refused; your project adds the approval (Chapter 11).
"""
import json
import sqlite3
import time


class AgentSession:
    def __init__(self, client, path, *, model, instructions, tools, handlers, ask_first=(), sleep=time.sleep, polls=200):
        self.client, self.model, self.instructions = client, model, instructions
        self.tools, self.handlers, self.ask_first = tools, handlers, frozenset(ask_first)
        self.sleep, self.polls = sleep, polls
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS conversations (conversation TEXT PRIMARY KEY, session_id TEXT, last_final TEXT)")
        self.db.commit()

    def close(self):
        self.db.close()

    def reply(self, conversation, text):
        """Send one message into the conversation's session and return the agent's final answer."""
        sessions = self.client.beta.agents.sessions
        row = self.db.execute("SELECT session_id, last_final FROM conversations WHERE conversation=?", (conversation,)).fetchone()
        if row is None:
            agent = {"model": self.model, "instructions": self.instructions, "tools": self.tools}
            sid = sessions.create(agent=agent, environment={"type": "openai_hosted"}, input=text).id
            before = None
        else:
            sid, before = row
            message = {"type": "agent.session.input.message",
                       "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}]}
            sessions.events.create(sid, events=[message])
        for _ in range(self.polls):
            self.sleep(1.5)
            state = sessions.retrieve(sid)
            actions = getattr(state, "required_actions", None)
            if actions:
                for action in [a.to_dict() for a in actions]:
                    sessions.events.create(sid, events=[self._result(action)])
            elif state.status == "idle" and (latest := self._newest_final(sid)) is not None and latest.id != before:
                break
            elif state.status in ("failed", "cancelled"):
                raise RuntimeError("session " + state.status)
        else:
            raise TimeoutError("the agent did not finish in time")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?)", (conversation, sid, latest.id))
        return "".join(c.get("text", "") for c in latest.to_dict()["content"])

    def _newest_final(self, sid):
        """The newest final answer in the session, or None. Newest first, because one page holds at most 100 items
        and a long conversation passes that: the new answer is then still on the first page."""
        page = self.client.beta.agents.sessions.items.list(sid, order="desc", limit=100)
        for item in page.data:
            if item.type == "message" and item.role == "assistant" and item.phase == "final_answer":
                return item
        return None

    def _result(self, action):
        name, call = action["name"], action
        if name in self.ask_first:
            output, ok = "Not done. This spends money. Ask the owner and wait for a clear yes.", False
        elif name not in self.handlers:
            output, ok = "Unknown tool.", False
        else:
            try:
                out = self.handlers[name](**action["arguments"])
                output, ok = (out if isinstance(out, str) else json.dumps(out)), True
            except Exception as error:
                output, ok = "Tool failed: " + type(error).__name__, False
        result = {"type": "agent.session.input.tool_result", "turn_id": call["turn_id"], "call_id": call["call_id"], "success": ok}
        result["output" if ok else "error"] = output  # the service reads output for a success and error for a failure
        return result
