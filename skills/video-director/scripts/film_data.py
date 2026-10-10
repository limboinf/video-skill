#!/usr/bin/env python3
"""把声音这边的结果导出成画面能直接用的 data.js：拍点（片内时间）、字幕、配音波形，外加建议切点。

用法：
  film_data.py --out data.js [--timeline timeline.json] [--cues cues.json] [--voice vo.wav]
  --timeline  video-audio 的 beat_timeline.py 输出（拍点已经换算成片内时间）
  --cues      video-audio 的 voiceover.py align 输出
  --voice     配音，导出每秒 100 段的峰值，画声带、做口型、做波形都用它

data.js 里有：BEATS、DOWNBEATS、CUES、VOWAVE = {rate, peaks}、CUTS（建议切点）。
建议切点 = 每句字幕开口前 0.05–0.6 秒里最近的一拍；那段里没有拍，就取开口前 0.15 秒。
画面按 CUTS 换镜头，声音和画面就天然对上（讲述片按句子切、切点又踩在拍上）。
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np


def peaks(path, rate=100):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x, per = np.abs(np.frombuffer(raw, np.float32)), 8000 // rate
    return [round(float(x[i:i + per].max()), 3) for i in range(0, len(x), per)]


def cut_before(start, beats):
    near = [b for b in beats if start - 0.6 <= b <= start - 0.05]
    return round(max(near) if near else max(0.0, start - 0.15), 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeline")
    ap.add_argument("--cues")
    ap.add_argument("--voice")
    a = ap.parse_args()

    tl = json.loads(Path(a.timeline).read_text()) if a.timeline else {}
    beats, downs = tl.get("beats", []), tl.get("downbeats", [])
    cues = json.loads(Path(a.cues).read_text()) if a.cues else []
    wave = {"rate": 100, "peaks": peaks(a.voice)} if a.voice else {"rate": 100, "peaks": []}
    cuts = sorted({0.0} | {cut_before(c["start"], beats) for c in cues[1:]})
    lines = [
        "// film_data.py 生成，不要手改：拍点（片内时间）、字幕、配音波形、建议切点",
        f"const BEATS = {json.dumps([round(b, 3) for b in beats])};",
        f"const DOWNBEATS = {json.dumps([round(b, 3) for b in downs])};",
        f"const CUES = {json.dumps(cues, ensure_ascii=False)};",
        f"const VOWAVE = {json.dumps(wave)};",
        f"const CUTS = {json.dumps(cuts)};",
    ]
    Path(a.out).write_text("\n".join(lines) + "\n")
    on = sum(1 for c in cuts[1:] if beats and min(abs(c - b) for b in beats) < 0.01)
    print(f"{a.out}：{len(beats)} 拍、{len(cues)} 条字幕、波形 {len(wave['peaks'])} 段；建议切点 {len(cuts) - 1} 个（{on} 个踩在拍上）")
    print("CUTS =", cuts)


if __name__ == "__main__":
    main()
