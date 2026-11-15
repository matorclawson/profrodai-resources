# Operator integration

This source composes an operator-only demonstration. The complete live rehearsal
has not run. Existing synthetic and startup evidence does not establish Telegram
exchange, model behavior, Sheet projection or a shipping notice.

The owning launcher supplies an `OperatorSettings` instance with a fixed run ID,
exact ERP company and Broker connection scope, existing private run directory,
approved one-row mapping and its hash, current source identity, exact local MCP
endpoint/Host/Origin, model project manifest and finite turn/run limits. It also
supplies the actual authenticated Broker client. No credential appears in those
settings. A plain settings object does not admit a transport or approve a map.

The mapping must use the recorded private chat string as the ERP user ID. The
customer ID is the producer's deterministic derivation from company, telegram
and that chat string. The enrollment observation must already be retained by the
admitted evidence adapter. Enrollment is never an order command.

The customer process enters `customer_runtime(settings, admitted_broker_client=...,
clock=...)`. It creates durable policy state, loads the native Mantle model and
yields the serialized operator runtime. `run_customer_loop` accepts the exact
retained cursor, stop event and bounded poll count. An interrupted or held turn
requires inspection of its original evidence before restart. There is no cursor
reset, automatic second mutation or replacement send key.

The producer process enters `producer_owner(settings, hosted_config, sheets_client=...,
sheets_expect=..., notice_client=..., notice_expect=..., clock=...)`. This is
another process path of the same owning launcher. It reads the actual customer
journal without writes, builds both receiving authorities, and creates one local
admin capability for that process. The returned service exposes the existing
ERP MCP app. Its `poll_once(admin_context)` is one explicit shipping-notice poll;
it is not a background retry loop. Finish workers and close the listener before
leaving the context, which closes the service and revokes the capability.

The real owner launch still must supply and review the paired device/client,
fresh fenced connection selections, approved private-chat map, exact Sheet and
headers, finite transport deadlines, producer listener lifecycle and bounded
poll trigger. The operator changes only the intended order's Status cell to
shipped. A customer message, model tool or plain admin string cannot trigger
that privileged path.

Before the complete run, qualify both source halves in their selected existing
interpreters. Preserve exact source pins, input bounds, retained responses,
model-call counts, business operation and projection results, and shutdown
outcomes. Run only inside the explicitly authorized operator window. Preserve
NOT_RUN until an actual complete run produces those results.
