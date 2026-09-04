from __future__ import annotations

import json
from pathlib import Path
import queue
import signal
import tempfile
import unittest

try:
    from .support import McpProcess
except ImportError:
    from support import McpProcess


class McpE2ETests(unittest.TestCase):
    def test_initialize_list_call_notifications_and_protocol_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mcp.txt"
            source.write_text("MCP E2E", encoding="utf-8")
            with McpProcess(root / "home") as server:
                server.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                initialized = server.response()
                self.assertEqual(initialized["id"], 1)
                self.assertEqual(initialized["result"]["serverInfo"]["name"], "specialist-runtime")

                server.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                with self.assertRaises(queue.Empty):
                    server.response(timeout=0.2)

                server.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                tools = server.response()
                self.assertEqual(len(tools["result"]["tools"]), 10)
                self.assertIn("vision_ocr", {tool["name"] for tool in tools["result"]["tools"]})

                server.send({
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "vision_ocr", "arguments": {"path": str(source)}},
                })
                call = server.response()
                self.assertEqual(call["id"], 3)
                self.assertFalse(call["result"]["isError"])
                structured = call["result"]["structuredContent"]
                self.assertEqual(structured["result"]["blocks"][0]["text"], "MCP E2E")
                self.assertEqual(json.loads(call["result"]["content"][0]["text"])["capability"], "vision.ocr")

                server.send({"jsonrpc": "1.0", "id": 4, "method": "tools/list"})
                invalid_version = server.response()
                self.assertEqual(invalid_version["id"], 4)
                self.assertEqual(invalid_version["error"]["code"], -32600)

                server.send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "missing", "arguments": {}}})
                invalid_call = server.response()
                self.assertEqual(invalid_call["error"]["code"], -32600)

                server.send_raw("{malformed json")
                parse_error = server.response()
                self.assertIsNone(parse_error["id"])
                self.assertEqual(parse_error["error"]["code"], -32700)

    def test_sigterm_closes_mcp_without_writing_non_json_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = McpProcess(Path(temporary) / "home").start()
            try:
                process = server.process
                self.assertIsNotNone(process)
                server.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                self.assertEqual(server.response()["id"], 1)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 0)
                with self.assertRaises(EOFError):
                    server.stdout.get(timeout=1)
            finally:
                # close() is idempotent even after SIGTERM.
                server.close()


if __name__ == "__main__":
    unittest.main()
