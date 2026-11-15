# Shop core with a custody-backed channel

The caller targets the seven commerce tools in the frozen contract. The new
operator-only Telegram composition has source and offline tests. It has not
completed a live end-to-end model, Telegram, Sheet and shipping-notice run.

Run the offline checks from this folder in an existing Python environment with
Pydantic v2 and JSON Schema support:

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use synthetic clients and model boundaries. They test real local journals,
concurrent read-only verification, exact draft approval, incomplete polling,
restart after uncertain sends and draining a worker during cancellation. They
make no provider call and do not qualify a live credential or customer binding.

`operator_composition.py` connects the admitted Broker client, evidence journal,
claim issuer, seven-tool policy, pinned MCP sessions and native Mantle lifecycle.
`producer_owner.py` composes the corresponding ERP customer authority and the
separate host-local admin capability in the producer process. It needs the
producer's receiving adapters, actual owner clients and exact Sheet settings.
The admin object never crosses a process boundary or enters a model tool.

`broker_evidence.py` retains the SDK request and response before exposing an
inbound observation. It requires a confirmed connection fence, a complete poll
chain and the approved operator mapping. An incomplete poll stays held. Raw
unusable replies remain present, so a later yes cannot erase the first reply.
A typed record, body hash or request header alone is not authentication.

The model chooses tools and arguments. The host renders actual ERP results and
the exact priced draft review. Confirmation needs a separate first affirmative,
the original confirmed review receipt, matching order and version, and current
run, map and draft lifetimes. Only one original draft is allowed per run. An
uncertain mutation or send never becomes permission to repeat it.

`native-agent` contains the model project, with seven imported native tools and
one configured OpenAI model. Credentials are environment references. The native
adapter requires the existing Rasa 3.21.0.dev5 and MCP 1.28.1 installations; it
installs nothing. The native prompt budget is the SDK's trimming setting, not a
proof that every request fits that token count. Actual model behavior and call
accounting still need the bounded rehearsal.

`OPERATOR-INTEGRATION.md` lists the explicit owner inputs and remaining run
qualification. These files do not choose a paired device, supply a credential,
start a listener or assert live readiness on import.

The code below describes the preserved earlier prototype. `erp_binding.py`
and its tests belong to that older contract; the current Mantle tool wrapper
does not import it. The old polling shell has not been connected to the new
core turn scope.

# Historical WhatsApp prototype

This lab is being built for November 16. The first exercise covers one failure:
a message arrives twice, or the process stops after a send but before saving
the reply. Repeating the send can give the customer two replies. Repeating a
confirmation can reserve stock twice.

Run the offline checks from this folder:

```sh
python3 -m unittest discover -s tests -v
```

They use Python's standard library and synthetic customer references. The 45
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

The poll cursor is persisted alongside attempt claims. Well-formed messages
outside the configured scope, time window, or text-only exercise are recorded
as `SKIPPED` and advance the cursor without reaching Mantle. Invalid transport
shapes or inconsistent ordering still stop the page before any delivery.
Broker paging repeats the entire boundary second. A new message ID can sort
before the saved ID in that second; it must still reach the journal. Existing
IDs deduplicate, and older seconds are refused as a transport-contract error.
Page completeness must be explicit. An incomplete final second is deferred and
reloaded whole after earlier complete seconds finish. If one second alone
exceeds the page limit, stop and escalate without partial delivery.
An unproven provider-history scan is different from response pagination. The
transport must map `FAILED_SAFE` / `REQUEST_REFUSED` /
`inbound_window_truncated` to a typed refusal with no page. It creates no claim,
delivery or cursor change; a later observation reuses the same saved cursor.

If a mutation response is lost before its operation ID arrives, the hold keeps
the original tool, arguments and message correlation. A private owner lookup
can identify that exact persisted operation; a subsequent `operation_status`
read resolves it. This maintenance path is absent from model tools and never
calls a mutation. Missing, mismatched or uncertain lookup results keep the
hold. The actual owner lookup transport has not been implemented or admitted.
Older holds without preserved metadata also stay held for an owner audit.
The hold preserves the original wire arguments. Owner lookup compares their
normalized semantic form and receives the producer's domain payload too.
Draft lines sort by product ID without merging duplicates; confirmation and
cancellation map their version fields to `version`, and handoff includes its
defaults. Recovery through either owner reconciliation or normal status
polling stores the recovered draft with its original message ID, prompt and
version before clearing the hold.

Phone hashes are not anonymization or a security boundary; their small input
space makes guessing possible. Keep the journal and any preserved arguments
private even though they contain no provider credentials.
