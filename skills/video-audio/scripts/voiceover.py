#!/usr/bin/env python3
"""生成配音，并把稿子对到真实说话段落上（给字幕用）。三种声音来源，稿子格式、输出格式都一样。

用法：
  voiceover.py voices [--source mine|heygen|gemini] [--language Chinese]   列出可用声音
  voiceover.py tts script.txt -o vo.wav [--source mine|heygen|gemini] [--voice ID或名字] [--engine orca] [--style "语气"]
  voiceover.py segments vo.wav                       静音检测切段，输出 JSON
  voiceover.py align script.txt vo.wav [-o cues.json] 把稿子按标点切成字幕，对到真实说话段落上（不需要 whisper）

声音来源：
  mine    你在 HeyGen 复刻的声音（默认）。不指定 --voice 就用第一个复刻声音
  heygen  HeyGen 公共声音库，--voice 填 voice_id（先用 voices --source heygen --language Chinese 查）
  gemini  Gemini 3.8 Flash TTS，--voice 填声音名（Kore、Puck、Charon……），--style 写语气（「轻松聊天」「沉稳讲述」）；
          密钥从环境变量 GEMINI_API_KEY 读

稿子统一用 <break time="0.3s"/> 写停顿（必须写秒）。交给 Gemini 时自动换成它的 <short pause> / <long pause>。
输出统一转成 48kHz 单声道 WAV。
注意：HeyGen 返回的 word_timestamps 是按字均分的假时间，不能直接拿来卡字幕；用 align。
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ENGINES = ["orca", "starfish", "elevenlabs"]  # 复刻声音的默认引擎经常不可用，按此顺序兜底
GEMINI_MODEL = "gemini-3.8-flash-tts"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_VOICE = "Kore"


def heygen(*args):
    exe = shutil.which("heygen") or str(Path.home() / ".local/bin/heygen")
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": {"message": r.stdout or r.stderr}}


def gemini(method, path, body=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("没有 GEMINI_API_KEY：先 export GEMINI_API_KEY=...（网络不通时再设 https_proxy）")
    req = urllib.request.Request(f"{GEMINI_API}/{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Gemini 报错 {e.code}：{e.read().decode()[:300]}")


def to_wav(src, out):
    """不管来源给的是什么格式，统一转成 48kHz 单声道 WAV。"""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "48000", out], check=True)


def list_voices(source, language):
    if source == "gemini":
        voices, token = [], ""
        while True:
            d = gemini("GET", "voices?pageSize=100" + (f"&pageToken={token}" if token else ""))
            voices += d.get("voices", [])
            token = d.get("next_page_token")
            if not token:
                break
        for v in voices:   # Gemini 的声音都能说 130 多种语言（含中文），language_code 只是它的母语口音
            print(f"{v['display_name']}\t{v.get('gender', '')}\t{v.get('pitch', '')}\t{v.get('persona', '')}\t{v.get('description', '')[:60]}")
        return
    args = ["voice", "list", "--type", "private" if source == "mine" else "public", "--limit", "50"]
    if language and source == "heygen":
        args += ["--language", language]
    for v in heygen(*args).get("data", []):
        print(f"{v['voice_id']}\t{v['name']}\t{v.get('gender', '')}\t{v.get('language', '')}\t{','.join(v.get('available_engines') or [])}")


def heygen_tts(text, voice_id, engine, out):
    for e in [engine] if engine else ENGINES:
        res = heygen("voice", "speech", "create", "--voice-id", voice_id, "--engine", e, "--text", text)
        if "data" in res:
            with tempfile.NamedTemporaryFile(suffix=Path(res["data"]["audio_url"].split("?")[0]).suffix or ".mp3") as f:
                urllib.request.urlretrieve(res["data"]["audio_url"], f.name)
                to_wav(f.name, out)
            return f"engine={res['data']['engine']}"
        print(f"[{e}] 失败：{res['error'].get('message', '')[:120]}", file=sys.stderr)
    sys.exit("所有引擎都失败了")


def gemini_breaks(text):
    """<break time="0.3s"/> → Gemini 的停顿标签：0.5 秒以内算短停顿，更长算长停顿。"""
    def sub(m):
        return "<long pause>" if float(m.group(1)) > 0.5 else "<short pause>"
    return re.sub(r'<break\s+time="([\d.]+)s"\s*/>', sub, text)


def gemini_tts(text, voice, style, out):
    part = {"type": "text", "text": gemini_breaks(text)}
    if style:   # 语气只能写在 style 里；写进正文会被当成台词念出来
        part["annotations"] = [{"type": "speech_metadata", "style": style}]
    d = gemini("POST", "interactions", {
        "model": GEMINI_MODEL, "input": [{"type": "user_input", "content": [part]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice or GEMINI_DEFAULT_VOICE}]}})
    audio = [c for st in d.get("steps", []) if st.get("type") == "model_output"
             for c in st.get("content", []) if c.get("type") == "audio"]
    if not audio:
        sys.exit("Gemini 没返回音频：" + json.dumps(d, ensure_ascii=False)[:300])
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(base64.b64decode(audio[-1]["data"]))
        f.flush()
        to_wav(f.name, out)
    return f"model={GEMINI_MODEL} voice={voice or GEMINI_DEFAULT_VOICE}"


def segments(wav, noise_db=-35, min_silence=0.2):
    log = subprocess.run(["ffmpeg", "-i", wav, "-af", f"silencedetect=n={noise_db}dB:d={min_silence}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav]))
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    spans, cursor = [], 0.0
    for s, e in zip(starts, ends + [dur]):
        if s - cursor > 0.05:
            spans.append([round(cursor, 2), round(s, 2)])
        cursor = e
    if dur - cursor > 0.05:
        spans.append([round(cursor, 2), round(dur, 2)])
    return spans


BREAK = re.compile(r"<break[^>]*/>")
CLAUSE_END = re.compile(r"(?<=[，。！？；、,.!?;])")
LINE_MAX = 16                                             # 一行字幕最多 16 个汉字宽


def han_count(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text))


MIN_CUE = 1.2   # 跟着配音念的字幕，每条至少显示这么久（没配音的字才按「字数 × 0.25s + 0.5s」，那条规则在 video-director）


def width(text):
    """显示宽度：汉字算 1，其他字符算 0.5。"""
    return han_count(text) + 0.5 * (len(text.replace(" ", "")) - han_count(text))


def weight(text):
    """念这段要多久的相对权重：汉字 1，英文单词按字母数 × 0.35，标点不算。"""
    words = re.findall(r"[A-Za-z0-9]+", text)
    return han_count(text) + sum(0.35 * len(w) for w in words) or 1


def split_units(script, level):
    """level=clause 按逗号句号切成分句；level=sentence 只按 <break> 切。返回 [(文字, 第几句)]。"""
    sents = [x.strip() for x in BREAK.split(script) if x.strip()]
    units = []
    for i, x in enumerate(sents):
        parts = [c.strip() for c in CLAUSE_END.split(x) if c.strip()] if level == "clause" else [x]
        units += [(re.sub(r"[，。！？；、,.!?;]+$", "", c), i) for c in parts]
    return units


def merge_lines_keep(cues):
    """同一句里相邻的分句，合起来不超过一行就并成一条字幕，分句之间用空格隔开。"""
    out = []
    for c in cues:
        last = out[-1] if out else None
        if last and last["_s"] == c["_s"] and width(last["text"] + c["text"]) + 1 <= LINE_MAX:
            last["text"] += " " + c["text"]
            last["end"] = c["end"]
        else:
            out.append(dict(c))
    return out


def match_gaps(spans, units):
    """把 N-1 个分句边界对到 M-1 个停顿上：按念的时长比例算每个边界的期望位置（只算说话时间，不算静音），
    动态规划选单调递增、总偏差最小的一组停顿。返回 (选中的停顿, 平均偏差秒数)；停顿不够用返回 None。"""
    n, m = len(units), len(spans)
    if n == 1:
        return [], 0.0
    if m - 1 < n - 1:
        return None
    talk = [b - a for a, b in spans]
    gap_pos = [sum(talk[: j + 1]) for j in range(m - 1)]      # 第 j 个停顿前已经说了多久
    total, ws = sum(talk), [weight(u) for u, _ in units]
    want = [total * sum(ws[: k + 1]) / sum(ws) for k in range(n - 1)]
    INF = float("inf")
    cost = [[INF] * (m - 1) for _ in range(n - 1)]
    back = [[-1] * (m - 1) for _ in range(n - 1)]
    for j in range(m - 1):
        cost[0][j] = abs(gap_pos[j] - want[0])
    for k in range(1, n - 1):
        best, arg = INF, -1
        for j in range(m - 1):
            if j > 0 and cost[k - 1][j - 1] < best:
                best, arg = cost[k - 1][j - 1], j - 1
            if best < INF:
                cost[k][j], back[k][j] = best + abs(gap_pos[j] - want[k]), arg
    j = min(range(m - 1), key=lambda x: cost[n - 2][x])
    err = cost[n - 2][j] / (n - 1)
    picked = []
    for k in range(n - 2, -1, -1):
        picked.append(j)
        j = back[k][j]
    return picked[::-1], err


SILENCE_STEPS = (0.2, 0.15, 0.1)   # 逗号处停得短的引擎（比如 orca）切不出来时，逐级放宽最短静音


def place(spans, units):
    """把 units 对到 spans 上，返回 ([每个 unit 的 (start, end)], 平均偏差秒数)；停顿不够返回 None。"""
    r = match_gaps(spans, units)
    if r is None:
        return None
    gaps, err = r
    cuts = [-1] + gaps + [len(spans) - 1]
    return [(spans[cuts[i] + 1][0], spans[cuts[i + 1]][1]) for i in range(len(units))], err


def merge_short(cues):
    """短于 MIN_CUE 的字幕并进同一句里更短的邻居（合并后最多两行）。"""
    i = 0
    while i < len(cues):
        c = cues[i]
        if c["end"] - c["start"] < MIN_CUE:
            nb = [j for j in (i - 1, i + 1) if 0 <= j < len(cues) and cues[j]["_s"] == c["_s"]
                  and width(cues[j]["text"] + c["text"]) + 1 <= 2 * LINE_MAX]
            if nb:
                j = min(nb, key=lambda k: cues[k]["end"] - cues[k]["start"])
                x, y = sorted((i, j))
                cues[x] = {"text": cues[x]["text"] + " " + cues[y]["text"], "_s": c["_s"],
                           "start": cues[x]["start"], "end": cues[y]["end"]}
                del cues[y]
                i = max(0, x - 1)
                continue
        i += 1
    return cues


def align(script, wav):
    """两层对齐：先按 <break> 的长停顿对整句（几乎不会错），再在每句的时间范围里对分句。"""
    sents = split_units(script, "sentence")
    coarse = segments(wav, min_silence=SILENCE_STEPS[0])
    r = place(coarse, sents)
    sent_t = r[0] if r else None
    if sent_t is None:
        sys.exit(f"说话段落只有 {len(coarse)} 段，比句子还少：在稿子里每句之间加 <break time=\"0.3s\"/> 重新合成，或者逐句合成")
    clauses = split_units(script, "clause")
    cues, level = [], "clause"
    for si, (s0, s1) in enumerate(sent_t):
        units = [u for u in clauses if u[1] == si]
        best = None
        for d in SILENCE_STEPS:                               # 几档静音门槛都试，挑和字数比例最吻合的一组
            fine = [sp for sp in segments(wav, min_silence=d) if sp[0] >= s0 - 0.01 and sp[1] <= s1 + 0.01]
            r = place(fine, units) if fine else None
            if r and (best is None or r[1] < best[1] - 1e-9):
                best = r
        got = best[0] if best else None
        if not got:                                            # 这句切不开，就整句一条
            units, got, level = [(sents[si][0], si)], [(s0, s1)], "mixed"
        cues += [{"text": u, "_s": si, "start": a, "end": b} for (u, _), (a, b) in zip(units, got)]
    cues = merge_short(merge_lines_keep(cues))
    for i, c in enumerate(cues):                              # 字幕显示到下一条开始；太短就提醒
        shown = (cues[i + 1]["start"] if i + 1 < len(cues) else c["end"] + 0.5) - c["start"]
        if shown < MIN_CUE:
            print(f"[提醒] 「{c['text']}」只显示 {shown:.2f}s，不到 {MIN_CUE}s：在稿子里这句后面加停顿", file=sys.stderr)
    return level, [{k: v for k, v in c.items() if k != "_s"} for c in cues]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sources = ["mine", "heygen", "gemini"]
    v = sub.add_parser("voices")
    v.add_argument("--source", choices=sources, default="mine")
    v.add_argument("--language", help="只对 heygen 公共声音生效，例如 Chinese")
    t = sub.add_parser("tts")
    t.add_argument("script")
    t.add_argument("-o", "--out", required=True)
    t.add_argument("--source", choices=sources, default="mine")
    t.add_argument("--voice", help="mine / heygen 填 voice_id；gemini 填声音名")
    t.add_argument("--engine", choices=ENGINES, help="只对 HeyGen 生效")
    t.add_argument("--style", help="只对 gemini 生效：语气，例如「轻松聊天，语速稍快」")
    s = sub.add_parser("segments")
    s.add_argument("wav")
    al = sub.add_parser("align")
    al.add_argument("script")
    al.add_argument("wav")
    al.add_argument("-o", "--out")
    a = ap.parse_args()

    if a.cmd == "voices":
        list_voices(a.source, a.language)
    elif a.cmd == "tts":
        text = Path(a.script).read_text().strip()
        if a.source == "gemini":
            info = gemini_tts(text, a.voice, a.style, a.out)
        else:
            voice = a.voice
            if not voice and a.source == "mine":
                voice = (heygen("voice", "list", "--type", "private", "--limit", "50").get("data") or [{}])[0].get("voice_id")
            if not voice:
                sys.exit("没有可用的声音：mine 要先在 HeyGen 复刻一个；heygen 要用 --voice 指定 voice_id")
            info = heygen_tts(text, voice, a.engine, a.out)
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out]))
        print(f"{a.out}\t{dur:.2f}s\tsource={a.source}\t{info}")
    elif a.cmd == "align":
        level, cues = align(Path(a.script).read_text(), a.wav)
        out = json.dumps(cues, ensure_ascii=False, indent=1)
        Path(a.out).write_text(out) if a.out else print(out)
        print(f"{len(cues)} 条字幕（按{'分句' if level == 'clause' else '整句'}对齐）" + (f" → {a.out}" if a.out else ""), file=sys.stderr)
    else:
        print(json.dumps(segments(a.wav)))


if __name__ == "__main__":
    main()
