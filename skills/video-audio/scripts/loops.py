#!/usr/bin/env python3
"""扫描 GarageBand（Apple Loops）素材库，按 BPM 和套件筛 loop。

用法：
  loops.py --bpms                      各 BPM 有多少个 loop
  loops.py --bpm 128 --kits            128 BPM 下有哪些套件（同套件 = 同一首歌拆出的分轨）
  loops.py --bpm 128 --grep Cascade    列出某套件的所有分轨和完整路径

BPM 从时长反推：时长 = 小节数 × 4 拍 × 60 / BPM，取能整除出整数 BPM 的那个。
结果缓存在 ~/.cache/video-audio/loops.json，素材库变了会自动重扫。
"""
import argparse
import json
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOTS = [Path("/Library/Audio/Apple Loops")]
CACHE = Path.home() / ".cache/video-audio/loops.json"
ROLE = re.compile(r"\s+(\d+|Beat|Bass|Synth|Guitar|Chords?|Keys|Pad|Lead|Topper|Layers|Kick|Snare|FX|Percussion|Arp|Piano|Stabs|Pluck|Riser|Hi-Hat|Vox|Drum\w*|Organ|Horns?|Sax|Strings|Effect)\b.*$")


def duration(path):
    out = subprocess.run(["afinfo", str(path)], capture_output=True, text=True).stdout
    m = re.search(r"estimated duration: ([\d.]+)", out)
    return float(m.group(1)) if m else 0.0


def infer_bpm(sec):
    for bars in (1, 2, 4, 8, 16):
        bpm = bars * 4 * 60 / sec if sec else 0
        if 70 <= bpm <= 180 and abs(bpm - round(bpm)) < 0.05:
            return round(bpm), bars
    return None, None


def scan():
    files = sorted(p for r in ROOTS if r.exists() for p in r.rglob("*.caf"))
    stamp = sum(p.stat().st_mtime for p in files)
    if CACHE.exists():
        cached = json.loads(CACHE.read_text())
        if cached.get("stamp") == stamp:
            return cached["loops"]
    with ThreadPoolExecutor(max_workers=8) as pool:  # 首次扫描几千个文件，并行 afinfo
        secs = list(pool.map(duration, files))
    loops = []
    for p, sec in zip(files, secs):
        bpm, bars = infer_bpm(sec)
        loops.append({"path": str(p), "name": p.stem, "genre": p.parent.name, "sec": round(sec, 3), "bpm": bpm, "bars": bars})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"stamp": stamp, "loops": loops}, ensure_ascii=False))
    return loops


def kit_of(name):
    return ROLE.sub("", name).strip() or name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bpm", type=int)
    ap.add_argument("--grep", help="名字包含该字符串（不区分大小写）")
    ap.add_argument("--bpms", action="store_true", help="统计各 BPM 数量")
    ap.add_argument("--kits", action="store_true", help="按套件汇总")
    a = ap.parse_args()

    loops = scan()
    if a.bpm:
        loops = [l for l in loops if l["bpm"] == a.bpm]
    if a.grep:
        loops = [l for l in loops if a.grep.lower() in l["name"].lower()]

    if a.bpms:
        for bpm, n in sorted(Counter(l["bpm"] for l in loops if l["bpm"]).items()):
            print(f"{bpm}\t{n}")
    elif a.kits:
        kits = Counter((l["genre"], kit_of(l["name"])) for l in loops)
        for (genre, kit), n in kits.most_common():
            print(f"{n}\t{genre}\t{kit}")
    else:
        for l in loops:
            print(f"{l['bpm']}\t{l['bars']}bar\t{l['sec']}s\t{l['path']}")


if __name__ == "__main__":
    main()
