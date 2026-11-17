"""Native adapter boundaries with fake Agent only; no SDK/model import."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from core_binding import CoreRequest
from native_mantle import NativeMantle, project_manifest


class NativeMantleTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_message_uses_registered_turn_identity_and_closes_once(self):
        now = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)
        seen = []

        class Message:
            def __init__(self, text, **kwargs):
                self.text, self.arguments = text, kwargs

        class Output:
            def __init__(self):
                self.messages = []

        class Agent:
            async def handle_message(self, message):
                seen.append(message)
                message.arguments["output_channel"].messages.append({"text": "synthetic"})

            async def close(self):
                seen.append("closed")
        native = NativeMantle(Agent(), user_message=Message, output_channel=Output, clock=lambda: now)
        request = CoreRequest("test_company", "telegram", "123", "test_request", "products", now,
                              now + timedelta(seconds=30))
        result = await native.turn(request)
        self.assertEqual(result, [{"text": "synthetic"}])
        self.assertEqual(seen[0].text, "products")
        self.assertEqual(seen[0].arguments["message_id"], "test_request")
        self.assertNotIn("123", seen[0].arguments["sender_id"])
        await native.close()
        await native.close()
        self.assertEqual(seen.count("closed"), 1)
        with self.assertRaises(PermissionError):
            await native.turn(request)

    def test_project_manifest_refuses_extra_or_symlinked_code(self):
        project = Path(__file__).resolve().parents[1] / "native-agent"
        manifest = project_manifest(project)
        self.assertIn("integrations.yml", manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            for name in ["agent.yml", "integrations.yml", "tools/commerce.py"]:
                (root / name).write_bytes((project / name).read_bytes())
            self.assertEqual(project_manifest(root), manifest)
            (root / "tools/extra.py").write_text("pass\n")
            with self.assertRaises(ValueError):
                project_manifest(root)
