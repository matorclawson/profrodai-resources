"""ERP process side of the same explicit operator launcher composition.

Loads no ERP SDK on import. Actual clients, fresh fences and HostedConfig come
from the admitted owner launch path; this factory neither pairs a device nor
selects a Sheet. Customer claims cross through readonly journals, while the
admin capability is minted and used ONLY inside this producer/poll process.
"""
from contextlib import contextmanager

from class_fixture_binding import ClassNoticeAuthority
from operator_admin import OperatorAdminCapability
from operator_composition import (OperatorSettings, check_mapping,
                                  launcher_admin_capability, producer_claim_resolver)


@contextmanager
def producer_owner(settings: OperatorSettings, hosted_config, *, sheets_client,
                   sheets_expect, notice_client, notice_expect, clock):
    """Yield one HostedPollRun for its MCP app and one explicit shipping poll."""
    from zeoerp.producer_authority import ProducerAuthority
    from zeoerp.admin_authority import OperatorAdminAuthority, CustomerAndAdminAuthority
    from zeoerp.hosted import HostedConfig, HostedPollRun, build_hosted_service
    from zeoerp.notices import NoticePermit

    settings = OperatorSettings.model_validate(settings)
    config = HostedConfig.model_validate(hosted_config)
    row = check_mapping(settings, clock)
    route = config.notice_route
    if (config.company_id != settings.scope.company_id
            or config.notice_connection_id != settings.scope.connection_id
            or route.channel != "telegram" or route.operation != "telegram.message.send"
            or route.recipient_field != "chat_id" or route.recipient_integer is not True
            or route.recipient_value(str(row.private_chat_id)) != row.private_chat_id):
        raise PermissionError("EXACT_OPERATOR_ERP_NOTICE_ROUTE_REQUIRED")
    epoch_clock = lambda: clock().timestamp()
    with producer_claim_resolver(settings, clock=clock) as resolver:
        with launcher_admin_capability(settings, clock=clock) as (issuer, capability):
            customer = ProducerAuthority(company_id=settings.scope.company_id, run_id=settings.run_id,
                fixture_map_sha256=settings.approved_map_sha256, not_after_epoch=settings.bounds.not_after_epoch,
                resolver=resolver, clock=epoch_clock)
            admin = OperatorAdminAuthority(capability_type=OperatorAdminCapability, verifier=issuer,
                launcher_identity=settings.launcher_identity, company_id=settings.scope.company_id,
                run_id=settings.run_id, not_after_epoch=settings.bounds.not_after_epoch, clock=epoch_clock)
            authority = CustomerAndAdminAuthority(customer=customer, admin=admin)
            mapping_authority = ClassNoticeAuthority(settings.approved_mapping,
                approved_sha256=settings.approved_map_sha256, scope=settings.scope,
                channel="telegram", permit_factory=NoticePermit)

            class RunNoticeAuthority:
                def authorize_notice(self, **arguments):
                    permit = mapping_authority.authorize_notice(**arguments)
                    expiry = min(permit.valid_until, int(settings.bounds.not_after_epoch))
                    if arguments["now"] >= expiry:
                        raise PermissionError("OPERATOR_NOTICE_RUN_EXPIRED")
                    return NoticePermit(**{**permit.model_dump(), "valid_until": expiry})

            context = admin.admin_context_for(capability, "operator-status-poll:" + settings.run_id)
            service = build_hosted_service(config, sheets_client=sheets_client, sheets_expect=sheets_expect,
                notice_client=notice_client, notice_expect=notice_expect, authority=authority,
                context_factory=customer, notice_authority=RunNoticeAuthority())
            try:
                yield HostedPollRun(service, context)
            finally:
                # Always finish this process's workers before exiting this
                # context. Issuer revocation follows service close immediately.
                service.close()
