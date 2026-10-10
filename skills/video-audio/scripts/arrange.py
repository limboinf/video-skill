#!/usr/bin/env python3
"""按小节网格把 GarageBand loop、HeyGen 素材、代码合成音效拼成一首曲子，并导出分轨。

用法：
  arrange.py plan.json                  → <out>/mix.m4a + <out>/stem_<名>.m4a
  arrange.py plan.json --bed bgm.wav    → 额外导出一条 -18 LUFS 的 wav，给视频当背景乐

plan.json：
{
  "bpm": 128, "bars": 8, "tail": 1.6, "lufs": -14, "out": "out",
  "clips": [
    {"gb": "02 Electro House/Cascade Synth Pad", "bars": [0, 2], "vol": 0.7},
    {"gb": "02 Electro House/Big Snare Roll Topper", "bars": [1, 2], "vol": 0.6, "offset_bars": 1},
    {"file": "sfx/impact.mp3", "hit_bar": 2, "peak": 0.455, "vol": 1.0, "stem": "heygen"},
    {"file": "sfx/sub.wav", "hit": 3.75, "vol": 0.8, "stem": "code"}
  ]
}
- gb：Apple Loops 里「流派目录/文件名」，不带 .caf；会循环铺满 bars 区间。
- file：一次性素材，hit_bar 或 hit（秒）是命中时刻，peak 是文件内峰值位置（默认 0）。
- stem：分轨名，gb 默认 "garageband"，file 默认 "sfx"。
相对路径以 plan.json 所在目录为准。
"""
import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

GB_ROOT = Path("/Library/Audio/Apple Loops/Apple")


def build(plan, base):
    bar = 60 / plan["bpm"] * 4
    clips = []
    for c in plan["clips"]:
        if "gb" in c:
            start, end = (b * bar for b in c["bars"])
            offset = c.get("offset_bars", 0) * bar
            clips.append({"path": GB_ROOT / f"{c['gb']}.caf", "loop": True, "start": start,
                          "trim": (offset, offset + end - start), "vol": c.get("vol", 1.0), "stem": c.get("stem", "garageband")})
        else:
            hit = c["hit"] if "hit" in c else c["hit_bar"] * bar
            clips.append({"path": base / c["file"], "loop": False, "start": max(0.0, hit - c.get("peak", 0)),
                          "trim": None, "vol": c.get("vol", 1.0), "stem": c.get("stem", "sfx")})
    total = plan["bars"] * bar + plan.get("tail", 0)
    return clips, total


def render(clips, total, out, lufs, codec_args):
    args, fc = ["ffmpeg", "-y", "-loglevel", "error"], []
    for i, c in enumerate(clips):
        if c["loop"]:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(c["path"])]
        cut = ""
        if c["trim"]:
            a, b = c["trim"]
            cut = f"atrim={a}:{b},asetpts=PTS-STARTPTS,afade=t=out:st={b - a - 0.02}:d=0.02,"  # 段尾 20ms 淡出防爆音
        ms = int(c["start"] * 1000)
        fc.append(f"[{i}]aresample=48000,aformat=channel_layouts=stereo,{cut}volume={c['vol']},adelay={ms}|{ms}[s{i}]")
    fc.append("".join(f"[s{i}]" for i in range(len(clips)))
              + f"amix=inputs={len(clips)}:normalize=0:duration=longest,apad,atrim=0:{total},"
              + f"afade=t=out:st={max(0, total - 1.2)}:d=1.2,loudnorm=I={lufs}:TP=-2[out]")  # AAC 编码会让峰值再冲高约 0.5 dB，留出余量
    subprocess.run(args + ["-filter_complex", ";".join(fc), "-map", "[out]", *codec_args, str(out)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--bed", help="额外导出 -18 LUFS 的 wav 背景乐")
    ap.add_argument("--no-stems", action="store_true")
    a = ap.parse_args()

    plan_path = Path(a.plan).resolve()
    plan = json.loads(plan_path.read_text())
    clips, total = build(plan, plan_path.parent)
    out = plan_path.parent / plan.get("out", "out")
    out.mkdir(parents=True, exist_ok=True)
    aac = ["-c:a", "aac", "-b:a", "256k"]

    render(clips, total, out / "mix.m4a", plan.get("lufs", -14), aac)
    print(f"{out / 'mix.m4a'}\t{total:.2f}s")
    if a.bed:
        render(clips, total, Path(a.bed), -18, ["-c:a", "pcm_s16le"])
        print(a.bed)
    if not a.no_stems:
        stems = defaultdict(list)
        for c in clips:
            stems[c["stem"]].append(c)
        for name, group in stems.items():
            render(group, total, out / f"stem_{name}.m4a", plan.get("lufs", -14), aac)
            print(out / f"stem_{name}.m4a")


if __name__ == "__main__":
    main()
