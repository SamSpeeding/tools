"""Search/detail/video-model protocol reconstructed from hongguo.py bytecode.

This module does not load the packaged Python code or use its licensing services.
It sends requests to an explicitly configured signer and the API host in config.
All server metadata is retained alongside the normalized fields.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from curl_cffi import requests as curl_requests
from hongguo_hm import model_headers


SEARCH_PATH = "/reading/bookapi/search/tab/v"
DETAIL_PATH = "/novel/player/multi_video_detail/v1/"
MODEL_PATH = "/novel/player/multi_video_model/v1/"
SINGLE_MODEL_PATH = "/novel/player/video_model/v1/"
IMAGE_SHRINK = (
    "W3siaW1hZ2VfdHlwZSI6MywiaW1hZ2Vfd2lkdGgiOjkwMCwic2hyaW5rX3R5cGUiOjN9LHsiaW1h\n"
    "Z2VfdHlwZSI6NCwiaW1hZ2Vfd2lkdGgiOjU0LCJzaHJpbmtfdHlwZSI6NH1d\n"
)


class APIError(RuntimeError):
    """Transport/protocol failure; raw response is retained when available."""

    def __init__(self, message: str, *, stage: str = "api", response: Any = None):
        super().__init__(message)
        self.stage = stage
        self.response = response


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _index(value: Any) -> int | None:
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        value = int(value.strip())
    return value if type(value) is int and 0 <= value <= 100000 else None


def _first_text(*values: Any) -> str:
    return next((value for value in values if isinstance(value, str) and value), "")


def _redact(value: Any) -> Any:
    """Keep useful request traces without copying credentials into the trace."""
    if isinstance(value, dict):
        return {
            key: "<redacted>" if str(key).lower() in {
                "x-sign-token", "x-tt-token", "cookie", "set-cookie", "authorization"
            } else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def parse_search_cell(cell: Any) -> dict | None:
    """Identify drama cells; non-drama search cards remain in raw_pages."""
    if not isinstance(cell, dict):
        return None
    sid = cell.get("book_id") or cell.get("search_result_id")
    if not sid or isinstance(sid, bool) or not isinstance(sid, (str, int)):
        return None
    detail = _object(cell.get("video_detail"))
    data = cell.get("video_data")
    if isinstance(data, list):
        data = data[0] if data else {}
    data = _object(data)
    inner = _object(data.get("video_detail"))
    count = detail.get("episode_cnt") or data.get("episode_cnt") or inner.get("episode_cnt")
    if not count:
        return None
    highlight = _object(_object(cell.get("search_high_light")).get("title")).get("text")
    highlight = re.sub(r"<[^>]+>", "", highlight) if isinstance(highlight, str) else ""
    return {
        "series_id": str(sid),
        "title": _first_text(inner.get("series_title"), detail.get("series_title"),
                             data.get("title"), highlight),
        "episode_cnt": count,
        "intro": _first_text(inner.get("series_intro"), detail.get("series_intro")),
        "score": data.get("score") or inner.get("score") or "",
        "play_cnt": data.get("play_cnt") or inner.get("series_play_cnt") or 0,
        "hot": data.get("rec_text") or "",
        "copyright": data.get("copyright") or "",
        "cover": data.get("cover") or inner.get("series_cover") or "",
        "vid": data.get("vid") or "",
        "duration": data.get("duration") or 0,
        "horiz_cover": data.get("horiz_cover") or "",
        "cover_tags": data.get("cover_tag_info_list") or [],
        "raw": cell,
    }


def search_cell_items(cell: Any):
    """Expand the drama, ranking, and linked-series shapes observed in search."""
    if not isinstance(cell, dict):
        return
    item = parse_search_cell(cell)
    if item:
        yield {**item, "source_type": "search"}

    ranking = cell.get("lynx_data")
    if isinstance(ranking, str):
        try:
            ranking = json.loads(ranking)
        except ValueError:
            ranking = None
    children = _object(ranking).get("cell_data")
    for child in children if isinstance(children, list) else []:
        videos = _object(child).get("video_data")
        for video in videos if isinstance(videos, list) else []:
            video = _object(video)
            sid = video.get("series_id") or _object(video.get("video_detail")).get("series_id")
            item = parse_search_cell({"book_id": sid, "video_data": [video]})
            if item:
                yield {**item, "source_type": "ranking", "raw": child}

    videos = cell.get("video_data")
    for video in videos if isinstance(videos, list) else []:
        related = _object(_object(video).get("video_detail")).get("video_detail_list")
        for detail in related if isinstance(related, list) else []:
            detail = _object(detail)
            # The outer card ID identifies a clip, not its linked drama.
            sid = detail.get("series_id_str") or detail.get("series_id")
            item = parse_search_cell({"book_id": sid, "video_detail": detail})
            if item:
                yield {**item, "source_type": "related_video", "raw": detail}


class HongguoAPI:
    def __init__(self, config_path, signer_url, signer_token, timeout=60, trace_path=None, device=None):
        self.config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
        for key in ("base_query", "session_headers"):
            if not isinstance(self.config.get(key), dict):
                raise ValueError(f"config.{key} must be an object")
        host = self.config.get("api_host", "")
        parsed = urlsplit("https://" + host)
        if not host or parsed.netloc != host or parsed.path or parsed.username:
            raise ValueError("config.api_host must contain only a host name (and optional port)")
        self.host = host
        self.signer_url = str(signer_url).rstrip("/")
        if urlsplit(self.signer_url).scheme not in {"http", "https"}:
            raise ValueError("signer_url must be an HTTP(S) URL")
        self.signer_token = signer_token
        if device is not None and (not isinstance(device, dict) or not isinstance(device.get("query"), dict)):
            raise ValueError("device must be an object containing a query object")
        self.device = device
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self.trace_path = Path(trace_path) if trace_path else None
        # Match the packaged HTTP transport and device overrides. The probe
        # changed both together, so it does not establish either factor alone.
        self.session = requests.Session()
        if urlsplit(self.signer_url).hostname in {"127.0.0.1", "localhost", "::1"}:
            self.session.trust_env = False
        self.api_session = curl_requests.Session(impersonate="chrome")

    def close(self):
        self.session.close()
        self.api_session.close()

    def _trace(self, record: dict):
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_redact(record), ensure_ascii=False) + "\n")

    def build_url(self, path: str, extra_query: dict | None = None) -> str:
        # The signed URL must use %20, not quote_plus's +, and preserve ordering.
        query = dict(self.config["base_query"])
        if self.device is not None:
            query.update(self.device["query"])
        query.update(extra_query or {})
        query["_rticket"] = str(int(time.time() * 1000))
        encoded = "&".join(f"{key}={quote(str(value), safe='')}" for key, value in query.items())
        return f"https://{self.host}{path}?{encoded}"

    def _req_headers(self, data: bytes | None = None) -> dict:
        headers = {str(key).lower(): str(value) for key, value in self.config["session_headers"].items()}
        if self.device is not None:
            if self.device.get("user_agent"):
                headers["user-agent"] = str(self.device["user_agent"])
            headers.pop("x-tt-token", None)
            headers.pop("cookie", None)
        headers["content-type"] = "application/json; charset=utf-8"
        # Never reuse a stale stub from config on a GET.
        headers.pop("x-ss-stub", None)
        if data is not None:
            headers["x-ss-stub"] = hashlib.md5(data).hexdigest().upper()
        return headers

    def _json_request(self, stage: str, method: str, url: str, headers: dict,
                      data: bytes | None, request_body: Any = None) -> dict:
        record = {"time": time.time(), "stage": stage, "method": method, "url": url,
                  "headers": dict(headers), "body": request_body}
        try:
            session = self.session if stage == "signer" else self.api_session
            response = session.request(method, url, headers=headers, data=data,
                                       timeout=self.timeout, allow_redirects=False)
            record["status"] = response.status_code
            record["response_headers"] = dict(response.headers)
            try:
                result = response.json()
            except ValueError as exc:
                record["response_text"] = response.text
                description = "empty response body" if not response.content else "response is not JSON"
                raise APIError(f"{stage}: HTTP {response.status_code}, {description}",
                               stage=stage, response=response.text) from exc
            record["response"] = result
            if not 200 <= response.status_code < 300:
                raise APIError(f"{stage}: HTTP {response.status_code}", stage=stage, response=result)
            if not isinstance(result, dict):
                raise APIError(f"{stage}: JSON response is not an object", stage=stage, response=result)
            return result
        except (requests.RequestException, curl_requests.exceptions.RequestException) as exc:
            record["error"] = str(exc)
            raise APIError(f"{stage}: {exc}", stage=stage) from exc
        except APIError as exc:
            record["error"] = str(exc)
            raise
        finally:
            self._trace(record)

    def _api_once(self, method: str, path: str, body: Any = None,
                  extra_query: dict | None = None) -> dict:
        url = self.build_url(path, extra_query)
        data = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = self._req_headers(data)
        sign_body = {"url": url, "headers": dict(headers)}
        sign_headers = {"content-type": "application/json"}
        if self.signer_token:
            sign_headers["X-Sign-Token"] = self.signer_token
        signed = self._json_request(
            "signer", "POST", self.signer_url + "/sign", sign_headers,
            json.dumps(sign_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), sign_body,
        )
        if "error" in signed:
            raise APIError(f"signer: {signed['error']}", stage="signer", response=signed)
        if not signed or any(not isinstance(v, (str, int)) for v in signed.values()):
            raise APIError("signer: response must be a nonempty header object", stage="signer", response=signed)
        signed_headers = {key.lower(): str(value) for key, value in signed.items()}
        headers.update(signed_headers)
        if path in (MODEL_PATH, SINGLE_MODEL_PATH):
            # Keep our persisted identity, exact URL/body and the other six JAR
            # headers. Only H/M use local v3 arithmetic, with the JAR's timestamp.
            # No old signatures, alternate host, device rotation or plugin call.
            try:
                if "x-khronos" not in signed_headers:
                    raise ValueError("JAR response has no x-khronos")
                headers.update(model_headers(url, data, headers))
            except (ValueError, TypeError, OSError) as exc:
                raise APIError(f"本地 Helios/Medusa 生成失败：{exc}", stage="signer") from exc
        headers.pop("accept-encoding", None)
        result = self._json_request("api", method, url, headers, data, body)
        for field in ("code", "status_code", "err_no", "error_code"):
            if field in result and result[field] not in (0, "0", None):
                message = result.get("message") or result.get("msg") or result.get("status_msg") or "request failed"
                raise APIError(f"API {path}: {field}={result[field]} ({message})", response=result)
        if result.get("error"):
            raise APIError(f"API {path}: {result['error']}", response=result)
        return result

    def search(self, keyword: str, page_count: int = 1, *, cursor: dict | None = None) -> dict:
        if not keyword.strip():
            raise ValueError("keyword must not be empty")
        if not 1 <= page_count <= 12:
            raise ValueError("page_count must be between 1 and 12")
        items, pages, warnings = [], [], []
        seen = set()
        cursor = cursor or {}
        offset = cursor.get("offset", 0)
        passback = cursor.get("passback", "")
        search_id = cursor.get("search_id", "")
        has_more = False
        next_cursor = None
        for page in range(page_count):
            next_cursor = None
            query = {"query": keyword, "tab_name": "feed", "search_source": "1",
                     "offset": str(offset), "count": "0", "use_correct": "true"}
            if passback:
                query["passback"] = passback
            if search_id:
                query["search_id"] = search_id
            result = self._api_once("GET", SEARCH_PATH, extra_query=query)
            pages.append(result)
            tabs = result.get("search_tabs")
            if not isinstance(tabs, list):
                raise APIError("search response lacks search_tabs list", response=result)
            if not tabs:
                has_more = False
                break
            tab = _object(tabs[0])
            cells = tab.get("data") or []
            if not isinstance(cells, list):
                raise APIError("search tab data is not a list", response=result)
            for cell in cells:
                for item in search_cell_items(cell):
                    if item["series_id"] not in seen:
                        seen.add(item["series_id"])
                        items.append(item)
            old_cursor = (str(offset), passback, search_id)
            offset = tab.get("next_offset") if tab.get("next_offset") is not None else offset
            passback = tab.get("passback") or passback
            search_id = tab.get("search_id") or search_id
            has_more = tab.get("has_more") in (True, 1, "1", "true")
            if not has_more:
                break
            if not cells or old_cursor == (str(offset), passback, search_id):
                warnings.append("服务器表示还有结果，但返回空页或分页游标未推进，已停止翻页。")
                break
            next_cursor = {"offset": offset, "passback": passback, "search_id": search_id}
        return {"keyword": keyword, "items": items, "raw_pages": pages,
                "warnings": warnings, "has_more": has_more, "next_cursor": next_cursor}

    def detail(self, series_id: str) -> dict:
        sid = str(series_id).strip()
        if not sid:
            raise ValueError("series_id must not be empty")
        body = {"biz_param": {
            "detail_page_version": 0, "disable_digg_stat": False,
            "disable_video_relate_book": False, "image_shrink_datas_str": IMAGE_SHRINK,
            "need_all_video_definition": False, "need_mp4_align": False,
            "screen_width_px": "900", "source": 7, "use_os_player": False, "use_server_dns": False,
        }, "series_id": sid}
        result = self._api_once("POST", DETAIL_PATH, body=body)
        entry = _object(result.get("data")).get(sid)
        if not isinstance(entry, dict) or not isinstance(entry.get("video_data"), dict):
            raise APIError(f"detail response lacks data[{sid!r}].video_data", response=result)
        data = entry["video_data"]
        raw_episodes = data.get("video_list")
        if not isinstance(raw_episodes, list):
            raise APIError("detail video_data lacks video_list", response=result)
        episodes, issues = [], []
        for position, raw in enumerate(raw_episodes, 1):
            if not isinstance(raw, dict):
                issues.append(f"Episode at list position {position} is not an object")
                episodes.append({"index": None, "vid": "", "title": "", "raw": raw,
                                 "error": "Malformed episode record"})
                continue
            index = _index(raw.get("vid_index"))
            vid = str(raw.get("vid") or "")
            if index is None:
                issues.append(f"Episode at list position {position} has invalid vid_index")
            if not vid:
                issues.append(f"Episode at list position {position} has no vid")
            episodes.append({**raw, "index": index, "vid": vid,
                             "title": _first_text(raw.get("title")),
                             "cover": raw.get("episode_cover") or raw.get("cover") or "",
                             "raw": raw})
        episodes.sort(key=lambda episode: (episode["index"] is None, episode["index"] or 0))
        expected = _index(data.get("episode_cnt"))
        if not episodes:
            issues.append("Server returned no episodes")
        if expected is not None and len(episodes) != expected:
            issues.append(f"Server reports {expected} episodes but returned {len(episodes)} records")
        indices = [ep["index"] for ep in episodes if ep["index"] is not None]
        vids = [ep["vid"] for ep in episodes if ep["vid"]]
        if len(indices) != len(set(indices)):
            issues.append("Server returned duplicate episode indices")
        if len(vids) != len(set(vids)):
            issues.append("Server returned duplicate episode video IDs")
        # Keep every video_data field, including cast, rights, and raw video_list.
        meta = {**data, "series_id": sid,
                "title": _first_text(data.get("series_title"), sid),
                "intro": data.get("series_intro") or "",
                "episode_cnt": expected if expected is not None else len(episodes),
                "status": "完结" if data.get("series_status") == 1 else "连载中",
                "cover": data.get("series_cover") or next((ep.get("cover") for ep in episodes if ep.get("cover")), ""),
                "play_cnt": data.get("series_play_cnt") or 0,
                "score": data.get("score") or data.get("douban_score") or data.get("rating") or ""}
        return {"series_id": sid, "meta": meta, "episodes": episodes,
                "raw_response": result, "issues": issues, "complete": not issues}

    def models(self, vids) -> dict:
        requested = list(dict.fromkeys(str(vid) for vid in vids if vid is not None and str(vid)))
        models, errors, raw_responses = {}, [], []
        for start in range(0, len(requested), 5):
            batch = requested[start:start + 5]
            body = {"biz_param": {
                "detail_page_version": 0, "device_level": 3, "disable_digg_stat": False,
                "disable_video_relate_book": False, "need_all_video_definition": True,
                "need_mp4_align": False, "use_os_player": False, "use_server_dns": False,
                "video_platform": 1024,
            }, "mixed_video_id_map": {"1": batch}}
            try:
                result = self._api_once("POST", MODEL_PATH, body=body)
            except APIError as exc:
                errors.append({"vids": batch, "error": str(exc), "stage": exc.stage,
                               "raw_response": exc.response})
                # A dead signer/transport affects subsequent batches too; do not
                # spend N timeouts on the same failure or hide the pending IDs.
                if exc.stage == "signer" or exc.response is None:
                    break
                continue
            raw_responses.append({"vids": batch, "response": result})
            data = _object(result.get("data"))
            for vid in batch:
                item = _object(data.get(vid))
                raw_model = item.get("video_model")
                try:
                    model = json.loads(raw_model) if isinstance(raw_model, str) else raw_model
                    if not isinstance(model, dict):
                        raise ValueError("video_model is absent or not an object")
                    raw_tracks = model.get("video_list")
                    if not isinstance(raw_tracks, list) or not raw_tracks:
                        raise ValueError("video_model.video_list is empty or not a list")
                    tracks = []
                    for position, track in enumerate(raw_tracks, 1):
                        if not isinstance(track, dict):
                            errors.append({"vids": [vid], "error": f"Track {position} is not an object"})
                            continue
                        meta = _object(track.get("video_meta"))
                        tracks.append({**track, "main_url": track.get("main_url"),
                                       "backup_url": track.get("backup_url"),
                                       "definition": meta.get("definition", track.get("definition")),
                                       "size": meta.get("size", track.get("size")),
                                       "bitrate": meta.get("bitrate", track.get("bitrate")),
                                       "raw": track})
                    usable = any(track.get("main_url") or track.get("backup_url") for track in tracks)
                    models[vid] = {"vid": vid, "tracks": tracks, "model": model,
                                   "raw_model": raw_model, "raw_response": item, "complete": usable}
                    if not usable:
                        errors.append({"vids": [vid], "error": "No main_url or backup_url in any track"})
                except (ValueError, TypeError) as exc:
                    errors.append({"vids": [vid], "error": str(exc), "raw_response": item})
        missing = [vid for vid in requested if not models.get(vid, {}).get("complete")]
        return {"models": models, "requested_vids": requested, "missing_vids": missing,
                "errors": errors, "raw_responses": raw_responses,
                "complete": not missing and not errors}
