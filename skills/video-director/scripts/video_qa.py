#!/usr/bin/env python3
"""成片画面自检：规格、黑帧、冻帧、硬切点、构图三项（空底、版式雷同、每秒变化），外加联系表和手机尺寸预览。
检查项和阈值移植自 chuspeeism/code-video-director 的 qa.py（MIT），见仓库 NOTICE.md。

用法：
  video_qa.py final.mp4 [--expect-size 1080x1920] [--expect-dur 30] [--out qa]
                        [--allow-solid-bg] [--fixed-layout]
  --allow-solid-bg  只给「纯色大底快切的动态排版」：不查画面空不空
  --fixed-layout    只给「固定界面的网页录屏、分步说明书」：不查版式雷同和每秒变化
输出（默认在成片旁边的 <名字>_qa/）：
  report.json   全部数字
  cuts.txt      硬切点，逗号分隔，直接喂给 video-audio 的 audio_qa.py --cuts 查切点落拍
  联系表.jpg     每 2 秒一帧，看整体节奏、景别轮换、有没有死画面
  手机尺寸.jpg   每秒一帧、360 宽，看手机上字还读不读得清
退出码：0 全部通过，3 有警告。声音（响度、静音、落拍）不在这里查，交给 audio_qa.py。
"""
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.exit("[错误] 缺 numpy：python3 -m pip install numpy")

# 阈值来自上游用原片和翻车片的校准：动画、实拍、地图类原片都在阈值内
EMPTY_BG_SHARE = 0.5     # 一帧里最多的那种颜色超过半屏，算「空底」；这类帧占比超过一半就报警
LAYOUT_SIM = 0.45        # 相隔 3 秒以上的两帧边缘分布的平均相似度，超过说明版式重复、机位不变
ADJACENT_SIM = 0.82      # 相邻两秒的平均相似度，超过说明像幻灯片翻页
MAX_FREEZE = 1.5         # 冻帧超过这么久算死画面（片尾定格除外）
TAIL_GRACE = 2.0         # 最后 2 秒的冻帧当落版，不报


def run(args, binary=False):
    return subprocess.run(args, capture_output=True, text=not binary, errors=None if binary else "ignore")


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path])
    if r.returncode != 0:
        sys.exit(f"[错误] ffprobe 读不了：{r.stderr.strip()[-300:]}")
    j = json.loads(r.stdout)
    v = next((s for s in j["streams"] if s.get("codec_type") == "video"), None)
    if not v:
        sys.exit("[错误] 文件里没有视频流")
    num, den = (v.get("avg_frame_rate") or "0/1").split("/")
    return {"width": int(v["width"]), "height": int(v["height"]),
            "fps": round(float(num) / float(den), 3) if float(den) else 0.0,
            "duration": round(float(j["format"].get("duration") or v.get("duration") or 0), 3)}


def scan(path, dur):
    """一次解码：黑帧、冻帧、整体变化大的硬切（scene > 0.3）。"""
    vf = "scale=640:-2,blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.003:d=1.5,select='gt(scene\\,0.3)',showinfo"
    err = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:v:0", "-vf", vf, "-an", "-f", "null", "-"]).stderr
    blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", err)]
    fs = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", err)]
    fe = [float(x) for x in re.findall(r"freeze_end:\s*([\d.]+)", err)]
    freezes = [(s, fe[i] if i < len(fe) else dur) for i, s in enumerate(fs)]
    cuts = [float(x) for x in re.findall(r"Parsed_showinfo.*?pts_time:\s*([\d.]+)", err)]
    return blacks, freezes, cuts


def gray_frames(path, w, h, fps=None):
    vf = (f"fps={fps}," if fps else "") + f"scale={w}:{h},format=gray"
    raw = run(["ffmpeg", "-v", "error", "-i", path, "-an", "-vf", vf, "-f", "rawvideo", "-"], binary=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)


def spike_cuts(path, fps):
    """补 scene 阈值漏掉的切换（暗色调、同一个房间、同一层界面下换机位）：
    相邻帧差超过邻近 8 帧中位数的 3 倍、且平均差 > 8，就算一刀。"""
    fr = gray_frames(path, 64, 36)
    if len(fr) < 3 or not fps:
        return []
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    out = []
    for i in range(len(d)):
        nb = np.concatenate([d[max(0, i - 4):i], d[i + 1:i + 5]])
        if d[i] > max(3.0 * (float(np.median(nb)) if len(nb) else 0.0), 8.0):
            t = round((i + 1) / fps, 3)
            if not out or t - out[-1] > 0.15:
                out.append(t)
    return out


def merge_cuts(a, b, gap=0.15):
    out = []
    for t in sorted(a + b):
        if not out or t - out[-1] > gap:
            out.append(round(t, 3))
    return out


def compose(path):
    """每秒一帧（160×90）：空底占比、版式雷同度、相邻两秒相似度。"""
    w, h = 160, 90
    raw = run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps=1,scale={w}:{h}", "-f", "rawvideo",
               "-pix_fmt", "rgb24", "-"], binary=True).stdout
    n = len(raw) // (w * h * 3)
    if n < 6:
        return None
    F = np.frombuffer(raw[: n * w * h * 3], np.uint8).reshape(n, h, w, 3).astype(np.int32)

    def bg_share(f):                      # 颜色量化成 8×8×8 档，最多的一档占多大面积
        k = (f[..., 0] // 32) * 64 + (f[..., 1] // 32) * 8 + f[..., 2] // 32
        return np.bincount(k.ravel(), minlength=512).max() / k.size

    def layout(f):                        # 10×10 块的边缘强度分布，归一化后点积就是相似度
        g = f.mean(2)
        e = np.abs(np.diff(g, axis=1))[:-1, :] + np.abs(np.diff(g, axis=0))[:, :-1]
        H, W = e.shape
        e = e[: H // 10 * 10, : W // 10 * 10].reshape(H // 10, 10, W // 10, 10).mean((1, 3)).ravel()
        e = e - e.mean()
        nn = np.linalg.norm(e)
        return e / nn if nn else e

    bs = np.array([bg_share(f) for f in F])
    L = np.array([layout(f) for f in F])
    far = [float(L[i] @ L[j]) for i in range(n) for j in range(i + 3, n)]
    adj = [float(L[i] @ L[i + 1]) for i in range(n - 1)]
    return {"empty_share": round(float((bs > EMPTY_BG_SHARE).mean()), 3),
            "layout_sim": round(float(np.mean(far)), 3) if far else None,
            "adjacent_sim": round(float(np.mean(adj)), 3), "samples": n}


def sheet(path, out, every, cols, width, dur):
    n = max(1, math.ceil(dur / every))
    vf = f"fps=1/{every},scale={width}:-2,tile={min(cols, n)}x{math.ceil(n / cols)}:padding=4:margin=4:color=0x202020"
    r = run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out)])
    return str(out) if r.returncode == 0 and out.exists() else None


def main():
    ap = argparse.ArgumentParser(description="成片画面自检")
    ap.add_argument("file")
    ap.add_argument("--expect-size")
    ap.add_argument("--expect-dur", type=float)
    ap.add_argument("--out")
    ap.add_argument("--allow-solid-bg", action="store_true")
    ap.add_argument("--fixed-layout", action="store_true")
    a = ap.parse_args()
    src = Path(a.file)
    out = Path(a.out) if a.out else src.with_name(src.stem + "_qa")
    out.mkdir(parents=True, exist_ok=True)

    results = []
    add = lambda name, ok, msg: results.append((name, ok, msg))
    info = probe(a.file)
    dur = info["duration"]

    if a.expect_size:
        got = f"{info['width']}x{info['height']}"
        add("尺寸", got == a.expect_size, f"{got}，期望 {a.expect_size}")
    if a.expect_dur:
        add("时长", abs(dur - a.expect_dur) <= a.expect_dur * 0.1, f"{dur:.2f}s，期望 {a.expect_dur:.2f}s ±10%")

    blacks, freezes, scene = scan(a.file, dur)
    blacks = [(s, e) for s, e in blacks if s > 0.1 and e < dur - 0.5]          # 片头淡入、片尾淡出不算
    add("黑帧", not blacks, "无" if not blacks else "、".join(f"{s:.1f}–{e:.1f}s" for s, e in blacks[:5]))
    dead = [(s, e) for s, e in freezes if e - s > MAX_FREEZE and s < dur - TAIL_GRACE]
    add("死画面", not dead, f"无超过 {MAX_FREEZE}s 的冻帧" if not dead else
        "、".join(f"{s:.1f}–{e:.1f}s" for s, e in dead[:5]) + "：加相机运动或换镜头，每 2–4 秒要有新东西")

    cuts = merge_cuts(scene, spike_cuts(a.file, info["fps"]))
    edges = [0.0] + cuts + [dur]
    longest = max(b - a_ for a_, b in zip(edges, edges[1:]))
    add("切点", True, f"{len(cuts)} 刀，最长一个镜头 {longest:.1f}s（只供参考，镜头长短看片型）")
    (out / "cuts.txt").write_text(",".join(f"{c:.3f}" for c in cuts))

    cs = compose(a.file)
    if cs:
        if not a.allow_solid_bg:
            add("画面空不空", cs["empty_share"] < 0.5, f"{cs['empty_share']:.0%} 的帧一半以上是同一种底色"
                + ("" if cs["empty_share"] < 0.5 else "：放大主体、铺满场景，别在空底上摆卡片"))
        if not a.fixed_layout:
            add("版式雷同", cs["layout_sim"] is None or cs["layout_sim"] <= LAYOUT_SIM, f"相隔 3 秒以上的画面相似度 {cs['layout_sim']}"
                + ("" if cs["layout_sim"] is None or cs["layout_sim"] <= LAYOUT_SIM else "：换景别、换角度、换构图"))
            add("每秒变化", cs["adjacent_sim"] <= ADJACENT_SIM, f"相邻两秒相似度 {cs['adjacent_sim']}"
                + ("" if cs["adjacent_sim"] <= ADJACENT_SIM else "：像幻灯片翻页，加相机运动、加镜头切换"))

    imgs = {"联系表": sheet(a.file, out / "联系表.jpg", 2, 6, 320, dur),
            "手机尺寸": sheet(a.file, out / "手机尺寸.jpg", 1, 8, 360, dur)}
    (out / "report.json").write_text(json.dumps(
        {"info": info, "blacks": blacks, "freezes": freezes, "cuts": cuts, "compose": cs, "images": imgs,
         "checks": [{"name": n, "ok": ok, "msg": m} for n, ok, m in results]}, ensure_ascii=False, indent=1))

    bad = 0
    print(f"== {src.name}：{info['width']}x{info['height']} {info['fps']}fps {dur:.2f}s")
    for name, ok, msg in results:
        bad += not ok
        print(f"{'✓' if ok else '⚠'} {name}：{msg}")
    print(f"预览图：{out / '联系表.jpg'}、{out / '手机尺寸.jpg'}（自检必须打开看）")
    print(f"查切点落拍：python3 <video-audio>/scripts/audio_qa.py {a.file} --cuts $(cat {out / 'cuts.txt'})")
    print("全部通过" if not bad else f"{bad} 项要改")
    sys.exit(3 if bad else 0)


if __name__ == "__main__":
    main()
