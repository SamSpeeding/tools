import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from hongguo import export_series


class ExportTests(unittest.TestCase):
    def api(self, failure=False):
        class FakeAPI:
            calls = 0

            def detail(self, sid):
                return {"meta": {"title": "测试", "episode_cnt": 6}, "complete": True,
                        "episodes": [{"index": i, "vid": str(i), "title": f"第{i}集"} for i in range(1, 7)]}

            def models(self, vids):
                self.calls += 1
                if failure:
                    return {"models": {}, "errors": [{"stage": "signer", "error": "offline", "raw_response": None}]}
                return {"models": {v: {"model": {"url_expire": 123}, "tracks": [
                    {"main_url": "https://cdn.test/low/" + v, "video_meta": {"size": 10}},
                    {"main_url": None, "backup_url": "https://cdn.test/high/" + v,
                     "video_meta": {"size": 20, "definition": "1080p"}, "encrypt_info": {"encrypt": True}}]}
                    for v in vids}}
        return FakeAPI()

    def test_export_all_episodes_uses_backup_and_retains_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = export_series(self.api(), "s", None, path, 0)
            data = json.loads(path.read_text())
            self.assertEqual(code, 0)
            self.assertEqual(data["resolved_count"], 6)
            self.assertEqual(data["episodes"][0]["download_url"], "https://cdn.test/high/1")
            self.assertTrue(data["episodes"][0]["encrypted"])
            self.assertEqual(data["episodes"][0]["url_expire"], 123)
            self.assertIn("加密：True", path.with_suffix(".txt").read_text())

    def test_fatal_signer_failure_keeps_partial_file_and_stops(self):
        api = self.api(failure=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "签名器"):
                    export_series(api, "s", None, path, 0)
            self.assertEqual(api.calls, 1)
            data = json.loads(path.read_text())
            self.assertEqual(data["status"], "partial")
            self.assertEqual(len(data["episodes"]), 6)
            self.assertEqual(data["resolved_count"], 0)


if __name__ == "__main__":
    unittest.main()
