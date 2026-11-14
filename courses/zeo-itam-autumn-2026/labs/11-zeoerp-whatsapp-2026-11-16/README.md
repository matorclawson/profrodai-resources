# Lucy's shop over WhatsApp

This lab is being built for November 16. The first exercise covers one failure:
a message arrives twice, or the process stops after a send but before saving
the reply. Repeating the send can give the customer two replies. Repeating a
confirmation can reserve stock twice.

Run the offline checks from this folder:

```sh
python3 -m unittest discover -s tests -v
```

They use Python's standard library and synthetic customer references. The 30
checks cover concurrent pollers, process restart, cursor advancement, changed
customer bindings, turn cancellation, and uncertain outcomes. They also check
exact draft versions, separate affirmative replies, closed tool arguments, and
one mutation per inbound message. They do not contact WhatsApp, execute a
Mantle turn, or confirm a real ERP order.

`channel_journal.py` claims a channel operation before dispatch. A duplicate
with the same binding returns its saved result reference or stays held. A
duplicate with a different customer or message is refused. A held operation
can finish after its original result is looked up; it never becomes a fresh
send automatically. Preserve the journal when restarting the process.

`channel_runtime.py` polls through an injected transport. It accepts only the
configured sandbox and participant allowlist, advances a provider cursor, and
replies to the current sender. A send confirmation digest is separate from a
provider message ID. A confirmed receipt hashes the canonical object
`{"message_sid":"<original SID>"}`; later delivery status does not alter that
binding. Candidate lookup must reproduce that exact digest. An ambiguous send
stays held; matching a body hash and
time window does not authorize a resend or prove which original send occurred.

`erp_binding.py` constructs correlation context from the current channel turn.
It never accepts sender, company, message ID, or confirmation authority from
model arguments. It records one mutation claim per message before dispatch.
An unresolved mutation blocks later writes for that customer. A read of the
original operation can resolve a hold; it cannot repeat the operation.

ERP owns the canonical review prompt. It independently reads the provider
record, verifies the sender and sandbox, and checks that the first reply after
the prompt is exactly `yes` or `confirm`. The local draft snapshot adds a
version and expiry check; it cannot replace ERP's provider verification.

`mantle_channel.py` and `mantle_tools.py` contain native adapter source for the
paired worker. They refuse to start without explicitly installed transports.
They have not been imported or exercised against Mantle in this checkout.

The complete lab still needs an admitted launcher, locked runtime, broker and
MCP transports, full producer-schema validation, model request accounting,
license custody, and an authorized phone exchange. The current code is a
mock-tested policy component, not a runnable WhatsApp agent. Preserve its
private journal and display only masked customer information in class. Never
put a provider credential in these files or pass it through a model tool.
