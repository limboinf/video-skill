#!/usr/bin/env python3
"""HeyGen 曲库 / 音效库：语义搜索 + 下载。

用法：
  heygen_audio.py search "airy whoosh transition" --type sound_effects
  heygen_audio.py search "guzheng wuxia sparse" --type music --limit 6
  heygen_audio.py search "driving rock, energetic" "cinematic drums, uplifting" --type music --min-dur 32
                                                   多个搜索词一次搜完、去重；--min-dur / --max-dur 按时长过滤
  heygen_audio.py fetch <id> -o sfx/whoosh.mp3
  heygen_audio.py fetch <id1>:sfx/a.mp3 <id2>:sfx/b.mp3   一次下载多个

search 会把结果（含预签名下载地址，7 天有效）存进 ./.heygen_audio.json，fetch 从这里取地址。
音效的 peak_offset 是文件内最响的时刻：排进 arrange.py 时填 "peak"，让命中点对齐画面。
需要先 `heygen auth login`；国内网络按需设置 HTTPS_PROXY。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CACHE = Path(".heygen_audio.json")


def heygen_bin():
    return shutil.which("heygen") or str(Path.home() / ".local/bin/heygen")


def search(query, kind, limit, min_score):
    cmd = [heygen_bin(), "audio", "sounds", "list", "--type", kind, "--query", query,
           "--limit", str(limit), "--min-score", str(min_score)]
    for attempt in range(3):  # 接口偶发 TLS 超时，重试即可
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(r.stdout)["data"]
        except (json.JSONDecodeError, KeyError):
            time.sleep(2 * (attempt + 1))
    sys.exit(f"搜索失败：{r.stdout or r.stderr}")


def download(url, out):
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    handlers = [{}] + ([{"https": proxy, "http": proxy}] if proxy else [])
    for attempt in range(4):  # 直连和代理轮流试：S3 地址有时直连更稳
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(handlers[attempt % len(handlers)]))
        try:
            with opener.open(url, timeout=60) as resp:
                Path(out).write_bytes(resp.read())
            return
        except OSError:
            time.sleep(2)
    sys.exit(f"下载失败：{url[:80]}…")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query", nargs="+")
    s.add_argument("--min-dur", type=float, default=0)
    s.add_argument("--max-dur", type=float, default=1e9)
    s.add_argument("--type", default="sound_effects", choices=["sound_effects", "music"])
    s.add_argument("--limit", type=int, default=6)
    s.add_argument("--min-score", type=float, default=0.4, help="默认 0.7 太严，常常搜不到")
    f = sub.add_parser("fetch")
    f.add_argument("ids", nargs="+", help="一个 id 配 -o；或者多个 id:输出路径")
    f.add_argument("-o", "--out")
    a = ap.parse_args()

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if a.cmd == "search":
        seen = set()
        for q in a.query:
            if len(a.query) > 1:
                print(f"## {q}")
            for x in search(q, a.type, a.limit, a.min_score):
                cache[x["id"]] = x
                if x["id"] in seen or not (a.min_dur <= x["duration"] <= a.max_dur):
                    continue
                seen.add(x["id"])
                print(f"{x['id']}\t{x['duration']:.2f}s\tpeak={x.get('peak_offset', 0)}\t{x['score']:.2f}\t{x.get('name', '')}\t{x['description'][:70]}")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    else:
        jobs = [(a.ids[0], a.out)] if a.out else [tuple(x.split(":", 1)) for x in a.ids]
        for i, out in jobs:
            if i not in cache:
                sys.exit(f"先用 search 搜到这个 id：{i}")
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            download(cache[i]["audio_url"], out)
            print(f"{out}\tpeak={cache[i].get('peak_offset', 0)}")


if __name__ == "__main__":
    main()
