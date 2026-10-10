#!/usr/bin/env python3
"""按一份 JSON 混出成片声音：配音 + 配乐（按人声自动压低）+ 音效（按峰值对齐），统一响度，导出分轨，并检查配乐有没有盖过人声。

用法：
  mix.py mix.json

mix.json：
{
  "dur": 30.5,                                   成片时长（秒）；不写就是配音长度 + 1.5
  "voice": "vo.wav",                             配音（可省略：纯配乐片）
  "music": {"file": "music/a.mp3", "start": 5.38, "fade_in": 0.5, "fade_out": 1.5},
                                                 start = 从曲子第几秒开始放（beat_timeline.py 算出来的 song_start）
  "under_voice_db": 15,                          有人说话时，配乐比人声低多少 dB（默认 15，至少 12）
  "gap_db": 4,                                   没人说话时，配乐比人声低多少 dB（默认 4）
  "sfx": [{"file": "sfx/whoosh.mp3", "hit": 4.11, "peak": 0.3, "gain_db": -4}],
                                                 hit = 画面上命中的时刻，peak = 文件里最响的位置（heygen_audio.py 会打印）
  "lufs": -14,                                   成片响度（默认 -14），真峰值限在 -1.5 dBTP
  "sfx_auto_fit": true,                          说话时压过人声的音效自动压到比人声低 6 dB（K 加权瞬时响度），并逐条报出来
  "tail_fade": 0.5,                              整轨最后淡出几秒（默认 0.5）：长尾音效到片尾还在响，不淡出会像被剪断
  "out": "mix.wav", "stems": "stems"             成片和分轨（voice / music / sfx）的位置
}
相对路径以 mix.json 所在目录为准。

为什么不用 sidechaincompress：压多少由音乐自己的响度决定，压完还可能盖过人声；
这里直接量人声和配乐的电平，按「低多少 dB」算出每一刻的音量，混完再量一遍核对。
退出码：0 通过；3 配乐或音效盖过人声（有人说话时：配乐低不到 12 dB，或某个音效低不到 6 dB）。
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from voiceover import segments  # noqa: E402  真实说话段落，和字幕对齐用的是同一套

SR = 48000
MIN_UNDER_DB = 12          # 有人说话时，配乐至少比人声低这么多
SFX_UNDER_DB = 6           # 有人说话时，每个音效至少比人声低这么多（音效短，可以比配乐响，但不能压过字）
LIMIT = 10 ** (-1.5 / 20)  # 真峰值上限 -1.5 dBFS


def load(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def save(path, x):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f64le", "-ar", str(SR), "-ac", "2", "-i", "-", str(path)],
                   input=np.ascontiguousarray(x).tobytes(), check=True)


def rms_db(x, mask=None):
    v = x[mask] if mask is not None else x
    return 20 * np.log10(np.sqrt(np.mean(v ** 2)) + 1e-12) if len(v) else -120.0


def lufs(x):
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        save(f.name, x)
        err = subprocess.run(["ffmpeg", "-nostats", "-i", f.name, "-af", "ebur128", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
    return float(err.rsplit("I:", 1)[1].split("LUFS")[0])


def place(track, clip, at):
    i = int(round(at * SR))
    a, b = max(0, i), min(len(track), i + len(clip))
    if b > a:
        track[a:b] += clip[a - i:b - i]


def smooth(v, sec):
    """长度 sec 的居中滑动平均（累加和实现，O(N)）。"""
    n = max(1, int(sec * SR))
    c = np.concatenate([[0.0], np.cumsum(v)])
    lo = np.clip(np.arange(len(v)) - n // 2, 0, len(v)); hi = np.clip(lo + n, 0, len(v))
    return (c[hi] - c[lo]) / np.maximum(hi - lo, 1)


def main():
    plan_path = Path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(__doc__)
    plan, base = json.loads(plan_path.read_text()), plan_path.parent
    voice = load(base / plan["voice"]) if plan.get("voice") else None
    dur = plan.get("dur") or (len(voice) / SR + 1.5 if voice is not None else sys.exit("没有配音时要写 dur"))
    n = int(round(dur * SR))
    tracks = {k: np.zeros((n, 2)) for k in ("voice", "music", "sfx")}

    speech = np.zeros(n, bool)
    if voice is not None:
        place(tracks["voice"], voice, 0)
        for a, b in segments(str(base / plan["voice"])):
            speech[int(a * SR):int(b * SR)] = True

    under, gap = max(MIN_UNDER_DB, plan.get("under_voice_db", 15)), plan.get("gap_db", 4)
    if plan.get("music"):
        m = plan["music"]
        x = load(base / m["file"])[int(m.get("start", 0) * SR):][:n]
        x = np.pad(x, ((0, n - len(x)), (0, 0)))
        fi, fo = int(m.get("fade_in", 0.5) * SR), int(m.get("fade_out", 1.5) * SR)
        env = np.ones(n)
        env[:fi] = np.linspace(0, 1, fi)
        env[n - fo:] *= np.linspace(1, 0, fo)
        ref_v = rms_db(tracks["voice"], speech) if speech.any() else -20.0
        ref_m = rms_db(x, np.abs(x).max(1) > 1e-4)
        # 有人说话的地方提前 0.15s 压下去、停下 0.3s 后再抬起来：把说话区间向两边放宽再抹平
        talk = smooth((smooth(speech.astype(float), 0.45) > 0).astype(float), 0.2)
        gain_db = (ref_v - lerp_db(gap, under, talk)) - ref_m
        tracks["music"] = x * (env * 10 ** (gain_db / 20))[:, None]

    events = []
    for s in plan.get("sfx", []):
        events.append([s, load(base / s["file"]) * 10 ** (s.get("gain_db", 0) / 20)])
    fitted = fit_sfx(events, tracks["voice"], speech, n) if voice is not None and plan.get("sfx_auto_fit", True) else []
    for s, clip in events:
        place(tracks["sfx"], clip, s["hit"] - s.get("peak", 0))

    tf = int(plan.get("tail_fade", 0.5) * SR)
    if tf:
        for v in tracks.values():
            v[n - tf:] *= np.linspace(1, 0, tf)[:, None]
    mix = sum(tracks.values())
    master = 10 ** ((plan.get("lufs", -14) - lufs(mix)) / 20)
    out = mix * master
    peak = np.abs(out).max()
    if peak > LIMIT:                                     # 少量超出的峰用软限幅压回来，不整体降音量
        out = np.tanh(out / LIMIT) * LIMIT
    save(base / plan.get("out", "mix.wav"), out)
    stems = base / plan.get("stems", "stems")
    for k, v in tracks.items():
        save(stems / f"{k}.wav", v * master)

    print(f"成片：{base / plan.get('out', 'mix.wav')}（{dur:.2f}s，目标 {plan.get('lufs', -14)} LUFS）；分轨：{stems}/voice|music|sfx.wav")
    bad = False
    if voice is not None and plan.get("music"):
        talk_mask = speech & (np.abs(tracks["music"]).max(1) > 0)
        d = rms_db(tracks["voice"], talk_mask) - rms_db(tracks["music"], talk_mask)
        worst = worst_window(tracks["voice"], tracks["music"], speech)
        ok = d >= MIN_UNDER_DB and worst >= MIN_UNDER_DB - 4
        bad |= not ok
        print(f"{'✓' if ok else '⚠'} 配乐不盖人声：说话时配乐平均比人声低 {d:.1f} dB（要 ≥ {MIN_UNDER_DB}），"
              f"最差的 1 秒低 {worst:.1f} dB（要 ≥ {MIN_UNDER_DB - 4}）"
              + ("" if ok else "：把 under_voice_db 调大，或换一首更稀疏的曲子"))
    if fitted:
        print("✓ 音效不压人声：以下音效原来压过了人声，已自动压到比人声低 %d dB（K 加权瞬时响度）：" % SFX_UNDER_DB)
        for line in fitted:
            print("    " + line)
    elif voice is not None and plan.get("sfx"):
        print("✓ 音效不压人声：说话时每个音效都比人声低 ≥ %d dB（K 加权瞬时响度）" % SFX_UNDER_DB)
    sys.exit(3 if bad else 0)


def momentary(x):
    """ffmpeg ebur128 的瞬时响度 M（400ms 窗口、K 加权，和人耳感受接近），每 0.1s 一个值。"""
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        save(f.name, x)
        err = subprocess.run(["ffmpeg", "-nostats", "-v", "verbose", "-i", f.name, "-af", "ebur128=framelog=verbose", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
    pts = re.findall(r"\bt:\s*([\d.]+)\s.*?\bM:\s*(-?[\d.]+|-inf)", err)
    if not pts:                                       # 解析不到就报错，绝不当成「通过」
        sys.exit("[错误] 读不到 ebur128 的瞬时响度，音效检查无法进行（ffmpeg 输出格式变了？）")
    t = [float(a) for a, _ in pts]
    m = [-120.0 if v == "-inf" else float(v) for _, v in pts]
    return np.array(t), np.array(m)


def fit_sfx(events, voice, speech, n):
    """说话时的每个音效：命中前后 0.5s 里，音效的瞬时响度最大值比人声低不到 SFX_UNDER_DB，就把它压下去。
    人声这一段太安静（还没开口）就不比。返回调整记录。"""
    tv, mv = momentary(voice)
    out = []
    for s, clip in events:
        a = int((s["hit"] - 0.1) * SR); b = int((s["hit"] + 0.4) * SR)
        if b <= 0 or a >= n or speech[max(0, a):min(n, b)].mean() < 0.3:
            continue
        solo = np.zeros((n, 2)); place(solo, clip, s["hit"] - s.get("peak", 0))
        ts, ms = momentary(solo[max(0, int((s["hit"] - 1.0) * SR)):min(n, int((s["hit"] + 1.5) * SR))])
        ts = ts + max(0.0, s["hit"] - 1.0)
        win = lambda tt, mm: mm[(tt >= s["hit"] - 0.1) & (tt <= s["hit"] + 0.5)]
        v, x = win(tv, mv), win(ts, ms)
        if not len(v) or not len(x) or v.max() < -45:
            continue
        d = v.max() - x.max()
        if d < SFX_UNDER_DB:
            cut = SFX_UNDER_DB - d
            clip *= 10 ** (-cut / 20)
            out.append(f"{s['hit']:6.2f}s {Path(s['file']).name:<18} 原来比人声{'高' if d < 0 else '低'} {abs(d):.1f} dB → 压低 {cut:.1f} dB"
                       + (f"（{s['note']}）" if s.get("note") else ""))
    return out


def lerp_db(a, b, p):
    return a + (b - a) * p


def worst_window(v, m, speech, win=1.0):
    """逐秒看：有人说话的每一秒里，人声比配乐高多少，取最小的那一秒（音乐突然变响的地方）。"""
    k, worst = int(win * SR), 99.0
    for i in range(0, len(v) - k, k // 2):
        sl = slice(i, i + k)
        if speech[sl].mean() > 0.5:
            worst = min(worst, rms_db(v[sl], speech[sl]) - rms_db(m[sl], speech[sl]))
    return worst


if __name__ == "__main__":
    main()
