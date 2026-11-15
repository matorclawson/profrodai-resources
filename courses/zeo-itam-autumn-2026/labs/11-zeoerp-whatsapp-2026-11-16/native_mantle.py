"""Native in-process Mantle lifecycle, with no public webhook or SDK patch.

Existing Codespace environment variables provide credentials. This module never
copies, writes or logs their values. Loading and turns are explicit async acts;
importing this source performs no SDK import, model call or network operation.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
from importlib.metadata import version
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core_binding import CoreBinding


class NativeModelSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project: Path
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_directory: Path


def project_manifest(project):
    expected = {"agent.yml", "integrations.yml", "tools/commerce.py"}
    actual = {p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()}
    if actual != expected or any(p.is_symlink() for p in project.rglob("*")):
        raise ValueError("EXACT_NATIVE_PROJECT_SOURCE_REQUIRED")
    return "\n".join(f"{hashlib.sha256((project / name).read_bytes()).hexdigest()}  {name}" for name in sorted(expected)) + "\n"


class NativeMantle:
    def __init__(self, agent, *, user_message, output_channel, clock):
        self.agent, self.message_type, self.output_type, self.clock = agent, user_message, output_channel, clock
        self.closed = False

    async def turn(self, request):
        if self.closed or self.clock() >= request.deadline:
            raise PermissionError("LIVE_NATIVE_TURN_REQUIRED")
        output = self.output_type()
        # Stable opaque sender ID scopes native memory to this actual customer.
        sender = hashlib.sha256((request.company_id + "\0" + request.channel + "\0" + request.user_id).encode()).hexdigest()
        await self.agent.handle_message(self.message_type(request.text, output_channel=output,
            sender_id=sender, input_channel="operator_telegram", message_id=request.request_id))
        return output.messages

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.agent.close()


@asynccontextmanager
async def native_mantle(source: NativeModelSource, *, binding: CoreBinding, clock):
    source = NativeModelSource.model_validate(source)
    if not isinstance(binding, CoreBinding):
        raise TypeError("ONE_ADMITTED_CORE_BINDING_REQUIRED")
    if hashlib.sha256(project_manifest(source.project).encode()).hexdigest() != source.manifest_sha256:
        raise PermissionError("REVIEWED_NATIVE_PROJECT_CHANGED")
    if version("rasa-pro") != "3.21.0.dev5" or version("mcp") != "1.28.1":
        raise RuntimeError("INSTALLED_NATIVE_RUNTIME_PIN_CHANGED")
    if not os.environ.get("RASA_LICENSE") or not os.environ.get("OPENAI_API_KEY"):
        raise PermissionError("EXISTING_CODESPACE_LICENSE_AND_MODEL_ENV_REQUIRED")
    if (os.environ.get("RASA_TELEMETRY_ENABLED") != "false"
            or os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") != "True"):
        raise PermissionError("EXPLICIT_OFFLINE_METADATA_CONFIGURATION_REQUIRED")
    # No fallback model, dummy key, secret file, provider probe or new server.
    from rasa.utils.licensing import validate_license_from_env
    validate_license_from_env()
    from rasa.mantle.model_archive.snapshot import package_model_archive
    from rasa.core.agent import load_agent
    from rasa.core.config.configuration import Configuration
    from rasa.core.config.available_endpoints import AvailableEndpoints
    from rasa.core.channels.channel import UserMessage, CollectingOutputChannel
    from rasa.mantle.processor import MantleMessageProcessor
    from mantle_tools import install_binding

    install_binding(binding)  # Same imported module used by archived tools.
    # Must be a new dedicated model directory; never overwrite a prior run.
    source.model_directory.mkdir(mode=0o700, exist_ok=False)
    packaged = package_model_archive(str(source.project / "agent.yml"), str(source.model_directory),
                                     fixed_model_name="itam-operator", validate=True)
    if packaged.code:
        raise RuntimeError("NATIVE_PROJECT_VALIDATION_FAILED")
    Configuration.initialise_empty_endpoints()
    Configuration.initialise_sub_agents(None)
    agent = None
    runtime = None
    try:
        agent = await load_agent(model_path=str(packaged.model), endpoints=AvailableEndpoints.from_dict({}))
        if not isinstance(agent.processor, MantleMessageProcessor):
            raise RuntimeError("NATIVE_MANTLE_PROCESSOR_REQUIRED")
        runtime = NativeMantle(agent, user_message=UserMessage, output_channel=CollectingOutputChannel, clock=clock)
        yield runtime
    finally:
        # Repeated cancellation must not skip native integration shutdown.
        import asyncio
        if runtime is not None or agent is not None:
            task = asyncio.create_task(runtime.close() if runtime is not None else agent.close())
            cancelled = False
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            task.result()
            if cancelled:
                raise asyncio.CancelledError
