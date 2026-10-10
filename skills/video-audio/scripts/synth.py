#!/usr/bin/env python3
"""代码合成音效：素材库里找不到、或要做成品牌资产的声音。

用法：
  synth.py riser  --sec 2.8 -o riser.wav     噪声上升（引向爆点）
  synth.py sub    --sec 1.4 -o sub.wav       808 低音下坠（爆点垫底）
  synth.py ding   -o ding.wav                FM 钟声双音（品牌收尾）
  synth.py whoosh --sec 0.8 -o whoosh.wav    带通噪声扫过（转场）
  synth.py tick   -o tick.wav                短促木质敲击（字幕/关键词）

所有声音用固定种子生成，同样参数每次输出一模一样。命中点（peak）打印在 stdout，
排进 arrange.py 时用 hit 对齐。
"""
import argparse
import wave

import numpy as np

SR = 48000


def t_axis(sec):
    return np.arange(int(sec * SR)) / SR


def one_pole_lowpass(x, cutoff_hz):
    """逐样本一阶低通，cutoff 可以是随时间变化的数组。"""
    alpha = 1 - np.exp(-2 * np.pi * np.broadcast_to(cutoff_hz, x.shape) / SR)
    out, acc = np.empty_like(x), 0.0
    for i in range(len(x)):
        acc += alpha[i] * (x[i] - acc)
        out[i] = acc
    return out


def riser(sec, rng):
    t = t_axis(sec)
    p = t / sec
    noise = one_pole_lowpass(rng.standard_normal(len(t)), 300 * 30 ** p)
    sweep = np.sin(2 * np.pi * np.cumsum(200 * 10 ** p) / SR)
    return (noise * 0.8 + sweep * 0.25) * p ** 2.2, sec  # 峰值在末尾


def sub(sec, rng):
    t = t_axis(sec)
    freq = 38 + 52 * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 2.6)
    click = rng.standard_normal(len(t)) * np.exp(-t * 400) * 0.3
    return np.tanh((body + click) * 1.8), 0.0


def ding(sec, rng):
    t = t_axis(sec)

    def bell(f0):
        mod = np.sin(2 * np.pi * f0 * 1.4 * t) * 2.2 * np.exp(-t * 6)
        return np.sin(2 * np.pi * f0 * t + mod) * np.exp(-t * 3.2)

    lag = int(0.09 * SR)
    hi = np.concatenate([np.zeros(lag), bell(1975.5)[:-lag]])  # B6 晚 90ms
    return bell(1318.5) * 0.7 + hi * 0.6, 0.0  # E6


def whoosh(sec, rng):
    t = t_axis(sec)
    p = t / sec
    env = np.sin(np.pi * p) ** 2  # 中间最响
    cutoff = 400 + 5000 * np.sin(np.pi * p)  # 亮度随音量一起起落
    noise = one_pole_lowpass(rng.standard_normal(len(t)), cutoff)
    return noise - one_pole_lowpass(noise, 250) * env, sec / 2


def tick(sec, rng):
    t = t_axis(sec)
    tone = np.sin(2 * np.pi * 1600 * t) * np.exp(-t * 90)
    knock = one_pole_lowpass(rng.standard_normal(len(t)), 3000) * np.exp(-t * 160)
    return tone * 0.6 + knock, 0.0


KINDS = {"riser": (riser, 2.8), "sub": (sub, 1.4), "ding": (ding, 2.2), "whoosh": (whoosh, 0.8), "tick": (tick, 0.12)}


def save(path, mono):
    mono = mono / max(1e-9, np.abs(mono).max()) * 0.9
    pcm = (np.stack([mono, mono], axis=1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=KINDS)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--sec", type=float, help="时长（秒），默认见各类型")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    fn, default_sec = KINDS[a.kind]
    mono, peak = fn(a.sec or default_sec, np.random.default_rng(a.seed))
    save(a.out, mono)
    print(f"{a.out}\tpeak={peak:.3f}s")


if __name__ == "__main__":
    main()
