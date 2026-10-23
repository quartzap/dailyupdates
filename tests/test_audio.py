import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from genai_digest import audio


class AudioTests(unittest.TestCase):
    def test_transient_edge_failure_retries_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "segment.mp3"

            async def save(filename):
                if client.save.await_count == 1:
                    raise TimeoutError()
                Path(filename).write_bytes(b"audio")

            client = SimpleNamespace(save=AsyncMock(side_effect=save))
            module = SimpleNamespace(Communicate=lambda *args, **kwargs: client)
            with patch.dict(sys.modules, {"edge_tts": module}), patch.object(audio.asyncio, "sleep", new_callable=AsyncMock):
                asyncio.run(audio._save_edge_segment("Hello", path, "voice", "+0%"))
            self.assertEqual(client.save.await_count, 2)
            self.assertTrue(path.exists())

    def test_edge_failure_uses_two_host_neural_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "script.txt"
            script.write_text("HOST A: Hello.\nHOST B: Welcome back.", encoding="utf-8")
            with patch.object(audio.shutil, "which", return_value="ffmpeg"), patch.object(audio, "_generate_dialogue_with_edge_tts", side_effect=RuntimeError("secret-token")), patch.object(audio, "_generate_with_piper") as fallback, self.assertLogs(audio.LOGGER) as logs:
                engine = audio.generate_mp3_from_script(script, Path(tmp) / "out.mp3")
            self.assertEqual(engine, "piper-dialogue")
            self.assertEqual([t.speaker for t in fallback.call_args.args[0]], [audio.HOST_A, audio.HOST_B])
            self.assertNotIn("secret-token", str(logs.output))

    def test_total_failure_removes_partial_mp3_and_redacts_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "script.txt"
            script.write_text("HOST A: Hello.", encoding="utf-8")
            output = Path(tmp) / "out.mp3"
            output.write_bytes(b"partial")
            with patch.object(audio.shutil, "which", return_value="ffmpeg"), patch.object(audio, "_generate_dialogue_with_edge_tts", side_effect=RuntimeError("private")), patch.object(audio, "_generate_with_piper", side_effect=RuntimeError("private")):
                with self.assertRaises(RuntimeError) as caught:
                    audio.generate_mp3_from_script(script, output)
            self.assertFalse(output.exists())
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
