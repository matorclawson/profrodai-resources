"""One OpenAI Agents API session per conversation (the Agents API, not the Agents SDK).

`client` is an `openai.OpenAI(...)` in a real run and `FakeAgentsClient` in tests; both have the same
`client.beta.agents.sessions` surface. A conversation keeps its hosted session across messages, and the
session id is stored in SQLite, so the agent still knows the conversation after a restart.

Tools are plain JSON specs plus our own Python functions. A tool named in `ask_first` never runs on the
model's say-so: it returns a message telling the model to ask the owner, and the owner's yes arrives as
an ordinary message in a later turn (the when-to-ask rule before spending).
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
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (conversation TEXT PRIMARY KEY, session_id TEXT, finals INTEGER)")
        self.db.commit()

    def close(self):
        self.db.close()

    def reply(self, conversation, text):
        """Send one message into the conversation's session and return the agent's final answer."""
        sessions = self.client.beta.agents.sessions
        row = self.db.execute("SELECT session_id, finals FROM sessions WHERE conversation=?", (conversation,)).fetchone()
        if row is None:
            agent = {"model": self.model, "instructions": self.instructions, "tools": self.tools}
            sid = sessions.create(agent=agent, environment={"type": "openai_hosted"}, input=text).id
            before = 0
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
            elif state.status == "idle" and self._finals(sid) > before:
                break
            elif state.status in ("failed", "cancelled"):
                raise RuntimeError("session " + state.status)
        else:
            raise TimeoutError("the agent did not finish in time")
        items = [i.to_dict() for i in sessions.items.list(sid, order="asc", limit=100).data]
        finals = [i for i in items if i.get("type") == "message" and i.get("role") == "assistant" and i.get("phase") == "final_answer"]
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)", (conversation, sid, len(finals)))
        return "".join(c.get("text", "") for c in finals[-1]["content"]) if finals else ""

    def _finals(self, sid):
        items = self.client.beta.agents.sessions.items.list(sid, order="asc", limit=100).data
        return sum(1 for i in items if i.type == "message" and i.role == "assistant" and i.phase == "final_answer")

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
        return {"type": "agent.session.input.tool_result", "turn_id": call["turn_id"],
                "call_id": call["call_id"], "success": ok, "output": output}
