from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from specialist.node import ComputeNode
from specialist.runtime import SpecialistRuntime

try:
    from .support import HttpService
except ImportError:
    from support import HttpService


class RemoteNodeE2ETests(unittest.TestCase):
    def test_authenticated_remote_node_transfers_real_input_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "remote.txt"
            source.write_text("remote boundary", encoding="utf-8")
            with HttpService(root / "node-home", token="node-token") as service:
                client = SpecialistRuntime(home=root / "client-home", backend="fallback")
                import os

                previous_token = os.environ.get("SPECIALIST_NODE_TOKEN")
                os.environ["SPECIALIST_NODE_TOKEN"] = "node-token"
                node = ComputeNode.create("node", capabilities=("vision.ocr",), latency_ms=1, metadata={"endpoint": service.url, "token_env": "SPECIALIST_NODE_TOKEN"})
                client.nodes.register(node)
                client._attach_remote_nodes()
                try:
                    value = client.run("vision.ocr", source, {"allow_remote": True, "local_only": False})
                    self.assertIsNone(value["error"])
                    self.assertEqual(value["result"]["blocks"][0]["text"], "remote boundary")
                    self.assertTrue(value["provider"].startswith("node:"))
                finally:
                    client.close()
                    if previous_token is None:
                        os.environ.pop("SPECIALIST_NODE_TOKEN", None)
                    else:
                        os.environ["SPECIALIST_NODE_TOKEN"] = previous_token


if __name__ == "__main__":
    unittest.main()
