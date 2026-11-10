import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hongguo_api import APIError, HongguoAPI, IMAGE_SHRINK


class APIProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"api_host": "example.invalid",
            "base_query": {"aid": "8662", "resolution": "1080*1920"},
            "session_headers": {"user-agent": "test"}}))
        self.api = HongguoAPI(self.config, "http://127.0.0.1:8080", "local-test-token")
        self.addCleanup(self.api.close)

    def test_exact_signed_url_body_hash_and_header_merge(self):
        calls = []

        def fake(stage, method, url, headers, data, request_body=None):
            calls.append((stage, method, url, headers, data, request_body))
            return {"X-Gorgon": "signed", "Accept-Encoding": "gzip"} if stage == "signer" else {"code": 0}

        with patch.object(self.api, "_json_request", side_effect=fake), patch("hongguo_api.time.time", return_value=123.456):
            self.api._api_once("POST", "/test", {"title": "剧 名"}, {"query": "a b/剧&"})
        signer, api = calls
        expected_url = "https://example.invalid/test?aid=8662&resolution=1080%2A1920&query=a%20b%2F%E5%89%A7%26&_rticket=123456"
        self.assertEqual(api[2], expected_url)
        self.assertEqual(api[4], '{"title":"剧 名"}'.encode())
        self.assertEqual(signer[5]["url"], expected_url)
        self.assertEqual(signer[5]["headers"]["x-ss-stub"], hashlib.md5(api[4]).hexdigest().upper())
        self.assertEqual(signer[3]["X-Sign-Token"], "local-test-token")
        self.assertEqual(api[3]["x-gorgon"], "signed")
        self.assertNotIn("accept-encoding", api[3])
        self.assertNotIn("X-Sign-Token", api[3])

    def test_search_pagination_nested_metadata_and_deduplication(self):
        cell = {"book_id": "series1", "video_data": [{"video_detail": {
            "series_title": "长标题", "series_intro": "完整介绍" * 40, "episode_cnt": 6}}]}
        page1 = {"search_tabs": [{"data": [cell, {"book_id": "book-only"}], "has_more": True,
                                  "next_offset": 10, "passback": "opaque", "search_id": "sid"}]}
        page2 = {"search_tabs": [{"data": [cell], "has_more": False}]}
        with patch.object(self.api, "_api_once", side_effect=[page1, page2]) as request:
            result = self.api.search("剧", 2)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["intro"], "完整介绍" * 40)
        self.assertEqual(result["raw_pages"], [page1, page2])
        second_query = request.call_args_list[1].kwargs["extra_query"]
        self.assertEqual((second_query["offset"], second_query["passback"], second_query["search_id"]),
                         ("10", "opaque", "sid"))

    def test_detail_preserves_records_and_reports_missing_episodes(self):
        raw = {"data": {"s1": {"video_data": {"series_title": "测试", "episode_cnt": 3,
            "custom_meta": {"retained": True}, "video_list": [
                {"vid_index": "2", "vid": "v2", "title": "x" * 100, "custom": "yes"},
                {"vid_index": "1", "vid": "v1"}]}}}}
        with patch.object(self.api, "_api_once", return_value=raw) as request:
            result = self.api.detail("s1")
        self.assertEqual(result["episodes"][0]["vid"], "v1")
        self.assertEqual(result["episodes"][1]["title"], "x" * 100)
        self.assertEqual(result["meta"]["custom_meta"], {"retained": True})
        self.assertFalse(result["complete"])
        self.assertTrue(result["issues"])
        body = request.call_args.kwargs["body"]
        self.assertEqual(body["biz_param"]["image_shrink_datas_str"], IMAGE_SHRINK)
        self.assertEqual(body["series_id"], "s1")

    def test_model_batches_keep_all_tracks_and_expose_missing_vid(self):
        def fake(method, path, body):
            data = {}
            for vid in body["mixed_video_id_map"]["1"]:
                if vid == "v6":
                    continue
                data[vid] = {"video_model": json.dumps({"unrecognized": "retained", "video_list": [
                    {"main_url": "https://cdn/720", "backup_url": "https://backup/720",
                     "video_meta": {"size": 50, "definition": "720p"}},
                    {"main_url": "https://cdn/1080", "backup_url": "https://backup/1080",
                     "video_meta": {"size": 90, "definition": "1080p"}}]})}
            return {"data": data}

        with patch.object(self.api, "_api_once", side_effect=fake) as request:
            result = self.api.models([f"v{n}" for n in range(7)] + ["v1"])
        self.assertEqual([len(call.kwargs["body"]["mixed_video_id_map"]["1"]) for call in request.call_args_list], [5, 2])
        self.assertEqual(len(result["models"]["v0"]["tracks"]), 2)
        self.assertEqual(result["models"]["v0"]["model"]["unrecognized"], "retained")
        self.assertEqual(result["missing_vids"], ["v6"])
        self.assertFalse(result["complete"])

    def test_nonzero_status_is_not_success(self):
        with patch.object(self.api, "_json_request", side_effect=[{"x-gorgon": "sig"}, {"code": 100, "message": "denied"}]):
            with self.assertRaisesRegex(APIError, "code=100"):
                self.api._api_once("GET", "/test")

    def test_dead_signer_does_not_retry_every_episode_batch(self):
        with patch.object(self.api, "_api_once", side_effect=APIError("unreachable", stage="signer")) as request:
            result = self.api.models([f"v{n}" for n in range(20)])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(result["missing_vids"]), 20)
        self.assertFalse(result["complete"])

    def test_trace_redacts_nested_credentials(self):
        trace = Path(self.temp.name) / "trace.jsonl"
        self.api.trace_path = trace
        self.api._trace({"headers": {"X-Sign-Token": "secret"},
                         "body": {"headers": {"cookie": "private", "x-ss-stub": "hash"}}})
        saved = trace.read_text()
        self.assertNotIn("secret", saved)
        self.assertNotIn("private", saved)
        self.assertIn("hash", saved)

    def test_device_override_removes_mismatched_session_credentials(self):
        self.api.config["session_headers"].update({"Cookie": "old", "X-TT-Token": "old"})
        self.api.device = {"query": {"aid": "123", "device_id": "new"}, "user_agent": "device-ua"}
        self.assertIn("aid=123&", self.api.build_url("/test"))
        self.assertIn("device_id=new", self.api.build_url("/test"))
        headers = self.api._req_headers()
        self.assertEqual(headers["user-agent"], "device-ua")
        self.assertNotIn("cookie", headers)
        self.assertNotIn("x-tt-token", headers)

    def test_recorded_live_search_response(self):
        fixture = Path(__file__).resolve().parent / "fixtures/search.json"
        if not fixture.exists():
            self.skipTest("live evidence fixture not present")
        raw = json.loads(fixture.read_text())
        with patch.object(self.api, "_api_once", return_value=raw):
            result = self.api.search("逆袭")
        first = result["items"][0]
        self.assertEqual(first["series_id"], "7689391720735181848")
        self.assertEqual(first["episode_cnt"], 111)
        self.assertIn("金牌班", first["title"])
        self.assertIn("record_info", first["raw"]["video_data"][0]["video_detail"])


if __name__ == "__main__":
    unittest.main()
