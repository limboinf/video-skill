#!/usr/bin/env python3
"""交付前的声音自检：时长、响度、真峰值、静音、结尾淡出、切点落拍。Agent 听不到，靠这些数据把关。

用法：
  audio_qa.py final.mp4 [--expect-dur 30] [--no-music]
                        [--cuts 1.2,3.4,... | --timeline timeline.json] [--beats-json timeline.json | --beats-src bgm.wav]
  --no-music    声明没有配乐：静音多是正常的（句间应当是真静音）
  --cuts        画面切点（秒），逗号分隔；或用 --timeline 读 beat_timeline.py 输出里每个镜头的起点
  --beats-json  直接用 beat_timeline.py 输出里的拍点（已经是片内时间）。优先用它：画面切点就是按这份拍点排的，
                重新测一遍反而可能测错（截出来的一段曲子常被测成半速，拍点少一半）
  --beats-src   拿哪个文件测拍点，默认就是被测文件。带大量 riser/音效的混音会把拍点测偏，
                有配乐分轨时传配乐，并且必须是「片子里实际播放的那一段」：曲子从第 5.38s 起放，
                就先 ffmpeg -ss 5.38 -t <片长> 裁出来再传。传整首原曲，拍点会整体错开，落拍比例不可信
退出码：0 全部通过，3 有警告。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

LUFS_RANGE = (-16.0, -12.0)   # 目标 -14，平台会按这附近标准化
MAX_TRUE_PEAK = -1.0          # 目标 -1.5 dBTP，超过 -1 就有削波风险
MAX_AV_GAP = 0.1              # 音轨和画面的时长差（秒）
ON_BEAT_WINDOW = 0.08         # 切点离拍点 80 毫秒以内算落拍


def ffprobe_durations(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                        "-of", "json", path], capture_output=True, text=True)
    out = {}
    for s in json.loads(r.stdout or "{}").get("streams", []):
        if s.get("duration"):
            out.setdefault(s["codec_type"], float(s["duration"]))
    return out


def measure(path):
    """一次解码同时跑静音检测（-50 dB、0.3 秒以上）和 ebur128（积分响度、真峰值）。"""
    af = "silencedetect=n=-50dB:d=0.3,ebur128=peak=true:framelog=quiet"
    err = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-vn", "-af", af, "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", err)]
    lufs = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", err)
    peak = re.findall(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS", err)
    return {"silences": list(zip(starts, ends + [None] * (len(starts) - len(ends)))),
            "lufs": float(lufs.group(1)) if lufs and lufs.group(1) != "-inf" else None,
            "true_peak": max(float(p) for p in peak if p != "-inf") if peak else None}


def mean_db(path, start, dur):
    err = subprocess.run(["ffmpeg", "-nostats", "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}", "-i", path,
                          "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf)", err)
    return float(m.group(1)) if m and m.group(1) != "-inf" else -91.0


def load_cuts(args):
    if args.timeline:
        shots = json.loads(Path(args.timeline).read_text())["shots"]
        return [s["start"] for s in shots if s["start"] > 0]
    return [float(c) for c in args.cuts.split(",") if c.strip()] if args.cuts else []


def main():
    ap = argparse.ArgumentParser(description="交付前的声音自检")
    ap.add_argument("file")
    ap.add_argument("--expect-dur", type=float)
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--cuts")
    ap.add_argument("--timeline")
    ap.add_argument("--beats-src")
    ap.add_argument("--beats-json")
    a = ap.parse_args()

    results = []
    add = lambda name, ok, msg: results.append((name, ok, msg))

    d = ffprobe_durations(a.file)
    if "audio" not in d:
        sys.exit(f"[错误] {a.file} 没有音轨")
    adur = d["audio"]
    if "video" in d:
        gap = adur - d["video"]
        add("音画等长", abs(gap) <= MAX_AV_GAP, f"音频 {adur:.2f}s / 画面 {d['video']:.2f}s（差 {gap:+.2f}s）"
            + ("" if abs(gap) <= MAX_AV_GAP else "：不够就补静音，多了就裁掉并淡出"))
    if a.expect_dur:
        add("时长", abs(adur - a.expect_dur) <= 0.5, f"{adur:.2f}s，期望 {a.expect_dur:.2f}s")

    m = measure(a.file)
    L, tp = m["lufs"], m["true_peak"]
    add("响度", L is not None and LUFS_RANGE[0] <= L <= LUFS_RANGE[1],
        f"{L} LUFS，目标 -14" + ("" if L and LUFS_RANGE[0] <= L <= LUFS_RANGE[1] else "：按 mixing.md 的 loudnorm 命令重做"))
    add("真峰值", tp is not None and tp <= MAX_TRUE_PEAK, f"{tp} dBTP，上限 {MAX_TRUE_PEAK}"
        + ("" if tp is not None and tp <= MAX_TRUE_PEAK else "：loudnorm 加 TP=-1.5"))

    silent = sum((e if e is not None else adur) - s for s, e in m["silences"])
    ratio = silent / adur if adur else 0.0
    if a.no_music:
        add("静音", True, f"静音占 {ratio:.0%}（无配乐，句间真静音是对的）")
    else:
        holes = [(s, e) for s, e in m["silences"] if s > 0.3 and (e if e is not None else adur) < adur - 0.3]
        add("静音", not holes, f"静音占 {ratio:.0%}" + ("" if not holes else
            "；片中有断档：" + "、".join(f"{s:.1f}–{e:.1f}s" for s, e in holes[:5]) + "，配乐应当铺满"))

    tail, body = mean_db(a.file, adur - 0.3, 0.3), mean_db(a.file, 0, adur)
    add("结尾淡出", tail < body - 6 or tail < -60, f"最后 0.3 秒 {tail:.1f} dB / 全片 {body:.1f} dB"
        + ("" if tail < body - 6 or tail < -60 else "：结尾像是突然断掉，最后 1–2 秒加 afade"))

    cuts = load_cuts(a)
    if cuts:
        if a.beats_json:
            tl = json.loads(Path(a.beats_json).read_text())
            an = {"beats": tl["beats"], "beat_period": tl["beat_period"], "bpm": tl["bpm"]}
        else:
            from beats import analyze
            an = analyze(a.beats_src or a.file)
        beats, period = an["beats"], an["beat_period"]
        on = [c for c in cuts if min(abs(c - b) for b in beats) <= ON_BEAT_WINDOW]
        chance = min(1.0, 2 * ON_BEAT_WINDOW / period)
        rate = len(on) / len(cuts)
        add("切点落拍", rate >= max(0.7, chance + 0.2),
            f"{len(on)}/{len(cuts)} 个切点在拍点 ±80ms 内（{rate:.0%}，随便切约 {chance:.0%}），BPM≈{an['bpm']:.1f}"
            + ("" if rate >= max(0.7, chance + 0.2) else "；没落拍的："
               + "、".join(f"{c:.2f}" for c in cuts if c not in on)[:200]))

    bad = 0
    for name, ok, msg in results:
        bad += not ok
        print(f"{'✓' if ok else '⚠'} {name}：{msg}")
    print("全部通过" if not bad else f"{bad} 项要改")
    sys.exit(3 if bad else 0)


if __name__ == "__main__":
    main()
