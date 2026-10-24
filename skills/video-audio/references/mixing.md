# 混音与响度

## 目标值

| 对象 | 目标 |
|---|---|
| 配乐素材（交给视频工程前） | -18 LUFS（`arrange.py --bed` 直接输出） |
| 人声说话时的配乐 | 比人声低 18 dB（至少 12 dB；最响的那一秒至少 8 dB）。配乐越密（鼓、贝斯多）取越低。`mix.py` 的 `under_voice_db` |
| 没人说话时（开头、句间长停顿、结尾） | 比人声低约 4 dB，让音乐抬起来。`mix.py` 的 `gap_db` |
| 转场、关键帧音效 | 峰值在人声下面，不抢字：`gain_db` 一般 -10 到 -4 |
| 成片 | -14 LUFS，真峰值 ≤ -1.5 dBTP（抖音、视频号、YouTube 都会按这个附近标准化） |

## 放进视频

默认（video-director 自己写代码渲染）：所有声音先用 ffmpeg 混成一条 `mix.wav`，渲染时 `render.mjs --audio mix.wav` 合进去。画面只负责画面，声音在这里做完。

用 `mix.py` 混，一份 JSON 写清楚所有声音：

```json
{ "dur": 30.5, "voice": "vo.wav",
  "music": {"file": "music/a.mp3", "start": 5.38, "fade_in": 0.5, "fade_out": 1.5},
  "under_voice_db": 18, "gap_db": 4,
  "sfx": [{"file": "sfx/whoosh.mp3", "hit": 4.11, "peak": 0.3, "gain_db": -6}],
  "lufs": -14, "out": "mix.wav", "stems": "stems" }
```

```bash
python3 scripts/mix.py mix.json
```

- 它先量人声说话时的电平和配乐的电平，按「说话时低 `under_voice_db`、没人说话时低 `gap_db`」算出每一刻的配乐音量（说话前 0.15s 压下去、停下 0.3s 后抬起来），不靠压缩器猜。
- 混完再量一遍：说话时配乐平均至少低 12 dB、最响的那一秒至少低 8 dB，不达标退出码 3。
- **音效也不许压过人声**：说话时每个音效的瞬时响度（K 加权，和人耳接近）至少比人声低 6 dB。超了的自动压下去，逐条报出来（`sfx_auto_fit`，默认开）。实测这条片子 35 个音效里有 10 个压过了人声，最响的转场快门比人声高 7.4 dB；末尾的「太突兀」就是这么来的。用 RMS 比会被低频轰骗（人耳对低频不敏感），所以用 ebur128 的瞬时响度。
- 音效按「开始 = 命中时刻 − 峰值位置」放，`peak` 填 `heygen_audio.py` 打印的值。
- 成片统一到 -14 LUFS，真峰值超过 -1.5 dBFS 的少量峰用软限幅压回来；分轨 `stems/voice|music|sfx.wav` 一起导出。

实测 30 秒介绍片：旧版手调的侧链压缩，说话时配乐只比人声低约 1.2 dB；`mix.py` 混同一首曲子低 14.9 dB，1.3 秒混完。

用户点名 HyperFrames 时：每个声音一个 `<audio>`，带 `id`，用 `data-start` / `data-duration` / `data-volume` 定位；压人声用时间线上的音量动画（tween 里写绝对音量）。音效多时用脚本生成 `<audio>` 块，不要手写。

其他剪辑软件：把 `bgm.wav`、`vo.wav` 和音效按时间表摆上轨道，配乐轨道做侧链压缩或手动画音量包络。

## 成片响度

视频工具渲染完后，统一做一次响度标准化，画面直接复制，不重新编码：

```bash
ffmpeg -i raw.mp4 -c:v copy -af "loudnorm=I=-14:TP=-2:LRA=11" -ar 48000 -c:a aac -b:a 192k final.mp4
```

## 交付前自检

```bash
python3 scripts/audio_qa.py final.mp4 --expect-dur 30 --timeline timeline.json --beats-src bgm.wav
```

一次查完：音画等长（差 ≤ 0.1s）、响度 -16 到 -12 LUFS、真峰值 ≤ -1 dBTP、片中有没有配乐断档、结尾有没有淡出、画面切点落在拍点 ±80ms 内的比例（要 ≥ 70%，且明显高于随便切）。没配乐的片子加 `--no-music`。退出码 3 就是还有项要改。

几条容易漏的：

- 音频长度等于视频长度。不够补静音，多了裁掉并淡出。
- 导出 AAC 后真峰值会比 loudnorm 设定值高约 0.5 dB，所以 `arrange.py` 设成 TP=-2，导出后正好落在 -1.5 附近。
- 「不要配乐」的片子，句间是真静音，不垫底噪。

## 手动验证命令

```bash
ffmpeg -i final.mp4 -af ebur128 -f null - 2>&1 | grep -E "^\s+I:" | tail -1     # 整体响度
ffmpeg -ss 6.1 -t 0.5 -i final.mp4 -af volumedetect -vn -f null - 2>&1 | grep mean   # 某段的电平，查配乐有没有进来
ffmpeg -i a.m4a -i b.m4a -filter_complex "[1]volume=-1[n];[0][n]amix=2:normalize=0,volumedetect" -f null - 2>&1 | grep max  # 两个版本相减，-90dB 以下就是同一个声音
ffmpeg -i mix.m4a -filter_complex "showwavespic=s=1200x200" -frames:v 1 wave.png   # 波形图看结构：引子、爆点、抽鼓有没有出现
```

交付时把整体响度、时长和「建议听哪几秒」一并告诉用户，比如「听 0:03.75 的爆点」。
