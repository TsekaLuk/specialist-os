import sys
import tempfile
import unittest
from pathlib import Path

from specialist.providers.ipc import JsonlProcessProvider, WorkerError
from specialist.runtime import SpecialistRuntime


class IPCTests(unittest.TestCase):
    def test_isolated_runtime_uses_worker_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "note.txt"
            source.write_text("isolated", encoding="utf-8")
            result = SpecialistRuntime(home=root / "home", isolate=True).run("ocr", source)
            self.assertIsNone(result["error"])
            self.assertEqual(result["result"]["blocks"][0]["text"], "isolated")
            self.assertTrue((root / "home" / "logs" / "vision__ocr.worker.log").exists())

    def test_isolated_worker_stays_warm_and_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "note.txt"
            source.write_text("warm", encoding="utf-8")
            runtime = SpecialistRuntime(home=root / "home", isolate=True)
            runtime.run("ocr", source, {"request": 1})
            process = runtime.providers["vision.ocr"]._process
            runtime.run("ocr", source, {"request": 2})
            self.assertIs(runtime.providers["vision.ocr"]._process, process)
            runtime.close()
            self.assertIsNone(runtime.providers["vision.ocr"]._process)

    def test_worker_timeout_is_structured(self):
        provider = JsonlProcessProvider("slow", "vision.ocr", "test", [sys.executable, "-c", "import time; time.sleep(1)"], timeout_seconds=0.01)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.txt"
            source.write_text("x", encoding="utf-8")
            with self.assertRaises(WorkerError) as caught:
                provider.infer(source, {}, type("Cache", (), {"home": Path(temp)})())
            self.assertEqual(caught.exception.code, "provider_timeout")

    def test_worker_invalid_json_and_crash_are_reported(self):
        for command, expected in [
            ([sys.executable, "-c", "print('not-json', flush=True)"], "worker_invalid_output"),
            ([sys.executable, "-c", "raise SystemExit(7)"], "worker_stream_failed"),
        ]:
            provider = JsonlProcessProvider("bad", "vision.ocr", "test", command, timeout_seconds=1)
            with tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "input.txt"
                source.write_text("x", encoding="utf-8")
                with self.assertRaises(WorkerError) as caught:
                    provider.infer(source, {}, type("Cache", (), {"home": Path(temp)})())
                self.assertEqual(caught.exception.code, expected)


if __name__ == "__main__":
    unittest.main()
