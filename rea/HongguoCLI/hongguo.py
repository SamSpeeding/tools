#!/usr/bin/env python3
"""搜索、选剧、导出地址，或选择集数下载可播放的 MP4。"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

from hongguo_signer import LocalSigner

ROOT = Path(__file__).resolve().parent


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def output_path(value, title, sid):
    if value and Path(value).suffix.lower() == ".json":
        return Path(value).resolve()
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(title)).strip(" .")[:70] or "drama"
    return (Path(value) if value else ROOT / "outputs") / f"{name}_{sid}.json"


def print_search_items(items, start=1):
    labels = {"ranking": "榜单推荐", "related_video": "视频关联"}
    for i, item in enumerate(items, start):
        label = labels.get(item.get("source_type"))
        suffix = f"  （{label}）" if label else ""
        print(f"{i:>3}. {item.get('title') or item['series_id']}  "
              f"[{item.get('episode_cnt', '?')}集]  ID={item['series_id']}{suffix}")


def search_status(found):
    for warning in found.get("warnings") or []:
        print(f"提示：{warning}", file=sys.stderr)
    print(f"本次读取 {len(found['raw_pages'])} 页，解析到 {len(found['items'])} 部剧。")
    if found.get("next_cursor"):
        print("服务器还有更多结果；选剧时输入 n 加载下一页，也可用 --pages 指定初始页数（1–12）。")
    elif not found.get("has_more"):
        print("服务器已返回最后一页。")


def choose(found, selected=None, *, api):
    items = list(found["items"])
    cursor = found.get("next_cursor")
    if not items and not cursor:
        raise RuntimeError("搜索没有返回可选择的剧。请换一个关键词。")
    print_search_items(items)
    if selected is not None:
        if not 1 <= selected <= len(items):
            raise ValueError(f"--select 必须在 1 至 {len(items)} 之间")
        return items[selected - 1]
    while True:
        more = "n 下一页，" if cursor else ""
        answer = input(f"选择剧的序号（{more}q 退出）：").strip()
        if answer.lower() == "q":
            raise KeyboardInterrupt
        if answer.lower() == "n" and cursor:
            print("加载下一页…", flush=True)
            page = api.search(found["keyword"], cursor=cursor)
            search_status(page)
            cursor = page.get("next_cursor")
            seen = {item["series_id"] for item in items}
            new = [item for item in page["items"] if item["series_id"] not in seen]
            print_search_items(new, len(items) + 1)
            items.extend(new)
            print(f"新增 {len(new)} 部，当前共 {len(items)} 部，可选择以上任意序号。")
            if not items and not cursor:
                raise RuntimeError("搜索没有返回可选择的剧。请换一个关键词。")
            continue
        try:
            number = int(answer)
            if 1 <= number <= len(items):
                return items[number - 1]
        except ValueError:
            pass
        print("请输入列表中的序号。")


def select_tracks(model):
    tracks = model.get("tracks") or []
    result = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        meta = track.get("video_meta") or {}
        result.append({"url": track.get("main_url") or track.get("url"),
                       "backup_url": track.get("backup_url"),
                       "definition": meta.get("definition", track.get("definition")),
                       "size": meta.get("size", track.get("size")),
                       "codec": meta.get("codec_type", track.get("codec_type")),
                       "encrypted": (track.get("encrypt_info") or {}).get("encrypt"),
                       "raw": track})
    def size(item):
        try:
            return int(item.get("size") or 0)
        except (TypeError, ValueError):
            return 0
    return sorted(result, key=size, reverse=True)


def save_export(path, export):
    atomic_json(path, export)
    lines = [f"剧名：{export['series'].get('title') or export['series_id']}",
             f"series_id：{export['series_id']}",
             f"导出时间：{export['exported_at']}",
             f"结果：{export['status']}；地址 {export['resolved_count']}/{len(export['episodes'])} 集",
             "地址为接口返回值，可能限时有效；标注加密的媒体不能保证直接播放。", ""]
    for episode in export["episodes"]:
        lines.append(f"第{episode.get('index', '?')}集  {episode.get('title', '')}  vid={episode.get('vid', '')}")
        if episode.get("download_url"):
            lines.append(f"清晰度：{episode.get('definition', '?')}；加密：{episode.get('encrypted', '未知')}；URL过期时间戳：{episode.get('url_expire', '未知')}")
            lines.append(episode["download_url"])
            if episode.get("backup_url"):
                lines.append("备用：" + episode["backup_url"])
        else:
            lines.append("未取得地址：" + episode.get("error", "尚未处理"))
        lines.append("")
    Path(path).with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")


def export_series(api, sid, search_result, destination, pause, detail=None):
    if detail is None:
        print(f"读取全剧详情：{sid}", flush=True)
        detail = api.detail(sid)
    meta = detail["meta"]
    episodes = detail["episodes"]
    if not episodes:
        raise RuntimeError("详情未返回剧集列表，无法导出地址。")
    path = output_path(destination, meta.get("title", sid), sid)
    export = {"schema_version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
              "source": "Hongguo signed API", "series_id": sid, "series": meta,
              "search_result": search_result, "detail": detail, "episodes": [],
              "models": {}, "model_responses": [], "errors": [],
              "status": "in_progress", "resolved_count": 0}
    # Keep every episode, including missing/invalid IDs, visibly in the export.
    for episode in episodes:
        export["episodes"].append({**episode, "download_url": None, "backup_url": None,
                                   "tracks": [], "status": "pending"})
    vids = list(dict.fromkeys(str(e["vid"]) for e in episodes if e.get("vid")))
    save_export(path, export)
    print(f"{meta.get('title', sid)}：详情返回 {len(episodes)} 集，开始获取地址。", flush=True)
    try:
        for start in range(0, len(vids), 5):
            batch = vids[start:start + 5]
            result = api.models(batch)
            export["models"].update(result.get("models") or {})
            export["model_responses"].extend(result.get("raw_responses") or [])
            export["errors"].extend(result.get("errors") or [])
            for episode in export["episodes"]:
                vid = str(episode.get("vid") or "")
                if vid not in batch:
                    continue
                model = export["models"].get(vid) or {}
                tracks = select_tracks(model)
                episode["tracks"] = tracks
                best = next((t for t in tracks if t.get("url") or t.get("backup_url")), None)
                if best:
                    episode.update(download_url=best.get("url") or best["backup_url"], backup_url=best.get("backup_url"),
                                   definition=best.get("definition"), encrypted=best.get("encrypted"),
                                   url_expire=(model.get("model") or {}).get("url_expire"), status="resolved")
                    episode.pop("error", None)
                else:
                    episode.update(status="missing", error="接口未返回此集可用的 main_url；详见 models/errors。")
            export["resolved_count"] = sum(bool(e["download_url"]) for e in export["episodes"])
            save_export(path, export)
            print(f"  已处理 {min(start+5, len(vids))}/{len(vids)}，取得 {export['resolved_count']} 集地址", flush=True)
            if any(e.get("stage") == "signer" or
                   (e.get("stage") == "api" and e.get("raw_response") is None)
                   for e in result.get("errors", [])):
                raise RuntimeError("签名器或网络请求失败，已停止后续批次；当前结果已保存。")
            if start + 5 < len(vids):
                time.sleep(pause)
    except BaseException as exc:
        export["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "partial"
        export["errors"].append({"message": str(exc) or "用户中止"})
        save_export(path, export)
        print(f"已保存当前结果：{path}", file=sys.stderr)
        raise
    for episode in export["episodes"]:
        if episode["status"] == "pending":
            episode.update(status="missing", error="剧集缺少 vid，无法查询地址。")
    export["status"] = ("complete" if export["resolved_count"] == len(episodes)
                        and detail.get("complete", True) else "partial")
    save_export(path, export)
    print(f"\nJSON（完整信息、全部清晰度）：{path}\nTXT（逐集主/备用地址）：{Path(path).with_suffix('.txt')}")
    print(f"结果：{export['status']}，共取得 {export['resolved_count']}/{len(episodes)} 集地址。")
    return 0 if export["status"] == "complete" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keyword", nargs="?", help="搜索词；省略则交互输入")
    parser.add_argument("--select", type=int, help="直接选择搜索结果序号（从1开始）")
    parser.add_argument("--series-id", help="直接按 series_id 导出，跳过搜索")
    parser.add_argument("--pages", type=int, default=1, help="初始搜索页数，默认1；选剧时可输入 n 继续翻页")
    parser.add_argument("--list-only", action="store_true", help="仅搜索并保存结果")
    parser.add_argument("--download", metavar="集号", help="下载集号，例如 1、1,3,5、2-6 或 all")
    parser.add_argument("--export-only", action="store_true", help="只导出全剧信息和地址，不询问下载")
    parser.add_argument("--quality", choices=("1080p", "720p", "540p", "480p", "360p"), default="1080p", help="下载清晰度，默认1080p")
    parser.add_argument("--download-dir", type=Path, default=ROOT / "downloads", help="视频保存目录，默认本项目 downloads/")
    parser.add_argument("--output", help="输出目录或 .json 文件路径，默认 outputs/")
    parser.add_argument("--app-dir", type=Path, default=ROOT / "vendor", help="运行资源目录，默认本项目 vendor/")
    parser.add_argument("--config", type=Path, default=ROOT / "config/config.json", help="API配置文件")
    parser.add_argument("--devices", type=Path, default=ROOT / "config/devices.json", help="设备配置文件")
    parser.add_argument("--device-index", type=int, default=0, help="随包设备配置索引，默认0；-1使用config原值")
    parser.add_argument("--java", help="java 可执行文件路径")
    parser.add_argument("--signer-url", help="使用已有签名器；令牌从 HG_SIGN_TOKEN 环境变量读取")
    parser.add_argument("--timeout", type=float, default=60, help="每请求超时秒数")
    parser.add_argument("--pause", type=float, default=0.2, help="每批地址查询之间的间隔秒数")
    parser.add_argument("--trace", type=Path, help="将请求过程记录到 JSONL 文件（鉴权字段脱敏）")
    args = parser.parse_args(argv)
    if args.pages < 1 or args.pages > 12 or args.timeout <= 0 or args.pause < 0:
        parser.error("pages 必须为1–12，timeout必须大于0，pause不得小于0")
    if args.list_only and args.series_id:
        parser.error("--list-only 与 --series-id 不能同时使用")
    if args.download is not None and (args.list_only or args.export_only or not args.download.strip()):
        parser.error("--download 需要非空集号，不能与 --list-only 或 --export-only 同时使用")
    try:
        from hongguo_api import HongguoAPI
    except ImportError as exc:
        parser.exit(1, f"依赖尚未就绪：{exc}\n请先运行：python3 -m pip install -r requirements.txt\n")
    keyword = args.keyword
    if not args.series_id and not keyword:
        keyword = input("输入剧名或关键词：").strip()
        if not keyword:
            parser.error("搜索词不能为空")
    device = None
    device_file = args.devices
    if args.device_index >= 0 and device_file.is_file():
        devices = json.loads(device_file.read_text(encoding="utf-8"))
        if args.device_index >= len(devices):
            parser.error(f"device-index 超出范围，设备数为 {len(devices)}")
        device = devices[args.device_index]
    with ExitStack() as stack:
        signer = None
        if args.signer_url:
            signer_url, token = args.signer_url, os.environ.get("HG_SIGN_TOKEN", "")
        else:
            print("启动本地签名器…", flush=True)
            signer = stack.enter_context(LocalSigner(args.app_dir, java=args.java))
            signer_url, token = signer.url, signer.token

        def finish(code):
            if signer is not None and code == 0:
                signer.mark_success()
            return code

        api = HongguoAPI(args.config, signer_url, token,
                        timeout=args.timeout, trace_path=args.trace, device=device)
        if hasattr(api, "close"):
            stack.callback(api.close)
        search_result = None
        if args.series_id:
            sid = args.series_id
        else:
            print(f"搜索：{keyword}", flush=True)
            found = api.search(keyword, page_count=args.pages)
            search_status(found)
            if args.list_only:
                path = output_path(args.output, keyword, "search")
                atomic_json(path, found)
                print_search_items(found["items"])
                print(f"搜索结果：{path}")
                return finish(0)
            search_result = choose(found, args.select, api=api)
            sid = str(search_result["series_id"])
        detail = None
        if args.download is not None or (sys.stdin.isatty() and not args.export_only):
            from hongguo_download import parse_episodes, download_selected
            print(f"读取剧详情：{sid}", flush=True)
            detail = api.detail(sid)
            episodes = detail['episodes']
            available = [e['index'] for e in episodes if e.get('index') is not None and e.get('vid')]
            if not available or len(available) != len(set(available)):
                raise RuntimeError('详情中的集号为空或重复，无法安全选集。')
            print(f"\n{detail['meta'].get('title', sid)} · 共 {len(episodes)} 集")
            print('可选集号：' + ', '.join(map(str, sorted(available))))
            if args.download is not None:
                selected = parse_episodes(args.download, available)
            else:
                while True:
                    answer = input('下载集号（如 1、1,3,5、2-6、all；回车仅导出地址，q退出）：').strip()
                    if answer.lower() == 'q':
                        raise KeyboardInterrupt
                    try:
                        selected = parse_episodes(answer, available)
                        break
                    except ValueError as exc:
                        print(exc)
            if selected:
                return finish(download_selected(api, detail, selected, args.download_dir,
                                                args.quality, args.timeout, args.app_dir))
        return finish(export_series(api, sid, search_result, args.output, args.pause, detail))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
