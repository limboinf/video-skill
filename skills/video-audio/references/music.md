# 配乐

## 先定来源

默认从 HeyGen 曲库找，找不到合适的再用 GarageBand 编曲。代码合成写不出一首像样的歌，不用来做配乐。

**曲风贴主题，不自由发挥**：产品介绍、项目宣传、发布片默认要动感、有推进力。实测反例：给 video-skill 介绍片配了 mid-century 爵士，用户反馈「很难听，不贴主题」。

| 需求 | 来源 |
|---|---|
| 大多数情况 | HeyGen 曲库：先从主题推出一句「这条片子听起来像什么」，按它搜 2–3 首同一方向的候选，做成试听给用户确认 |
| 选定的曲子要卡画面节拍点 | 还是那首曲子：`beats.py` 测拍点和高潮，`beat_timeline.py` 让高潮对准关键时刻（见下文「现成曲子怎么卡拍」） |
| 曲库里没有合适的，又必须按小节精确编排 | GarageBand（`loops.py` + `arrange.py`）。按 `loops.py --kits` 列出的套件挑曲风，别默认电子套件 |

**搜索词写法**：能量 + 乐器 + 情绪，英文效果更好，一次传 3–4 个词：`heygen_audio.py search "词1" "词2" --type music --min-dur <片长+2>`。少用 `upbeat corporate` 这类万能词，搜出来都是同一种「企业宣传 BGM」。动感方向的例子：`driving indie rock, punchy drums, confident`、`cinematic hybrid percussion, building, triumphant`、`funky bass groove, bright horns, energetic`、`hard-hitting hip-hop beat, bold, modern`。

**选曲看三样**：时长够（片长 + 2 秒）；`beats.py` 测出有爆发点（高潮候选的低频跳升 ≥ 6 dB），能对准片子的关键时刻；说话段别太密（主歌段落有人声、满编鼓组的曲子，压到 -15 dB 还是会抢）。

**和最近的作品拉开**：读 `~/.video-skill/作品记录.md`，最近 3 条用过的曲风、主乐器不重复。

本机 GarageBand 默认只有基础素材库。缺某类乐器时，请用户在 GarageBand「声音资源库」里下载扩展包，`loops.py` 会自动重新扫描。

## GarageBand：从选套件到编排

### 1. 选 BPM 和套件

```bash
python3 scripts/loops.py --bpms                    # 各 BPM 的数量，128 / 125 / 120 最多
python3 scripts/loops.py --bpm 128 --kits          # 某 BPM 下的套件
python3 scripts/loops.py --bpm 128 --grep Cascade  # 套件里的分轨
```

- **BPM 从时长反推**：一小节 = 4 × 60 / BPM 秒，loop 时长一般是 1/2/4/8 小节的整数倍。
- **同一套件的分轨可以放心叠**（同速同调）。鼓组 loop（Beat、Kick、Snare、Topper）没有调性，同 BPM 就能和任何套件搭。
- 用过的组合（只是记录，不是推荐，下一条换别的）：
  - Disco Funk「Hang Tight」116 BPM：鼓、合成器贝斯、和弦、吉他、琶音、镲、上升音效。偏律动，适合产品介绍。
  - Electro House「Cascade」128 BPM：垫音、钢琴、贝斯、主旋律、和弦、拨弦，鼓用 Blueprint Beat + Big Room Kick。偏动感，适合 15 秒短曲。

### 2. 用小节网格去找画面节拍点

做法是**找画面里恰好落在小节线附近的高潮**，而不是硬把音乐拉伸到画面上。

1. 列出画面节拍点（秒）：爆点、转场、盖章、揭晓。
2. 算出所有小节线：0、B、2B、3B……（B = 240 / BPM）。
3. 把编排的关键动作放到离节拍点最近的小节线上：进鼓、抽鼓、再进鼓、收尾。误差在 ±0.3s 内，观众感觉就是同步的。
4. 实在对不上时，优先挪画面动画几百毫秒，其次换 BPM。

### 3. 编排套路（短视频够用）

| 结构 | 用途 | 做法 |
|---|---|---|
| 引子 → 进鼓 | 开场钩子 | 前 1–2 小节只放垫音/和弦/镲，在第一个爆点进鼓、贝斯 |
| 抽鼓 → 再进鼓 | 制造第二个高潮 | 高潮前 1–2 小节抽掉鼓，只留琶音/拨弦，叠上升音效（截取它最后几秒，让顶点落在小节线上） |
| 结尾一击 | 收尾 | 最后一个小节线上放冲击或低音轰鸣 + 品牌叮声，再留 1–2 秒尾音 |

### 4. 写 plan.json，混出来

`arrange.py` 的 plan 格式见脚本头注释。同一个套件在不同段落重复出现时，写成多条 clip，用 `bars` 指定区间。

```bash
python3 scripts/arrange.py plan.json                 # 成曲 -14 LUFS + 各来源分轨
python3 scripts/arrange.py plan.json --bed bgm.wav   # 另出一条 -18 LUFS 的 wav，给视频当背景乐
```

## 现成曲子怎么卡拍：测拍点、让高潮砸在关键时刻

HeyGen 曲库、用户给的歌都没有小节网格，先测出来：

```bash
python3 scripts/beats.py song.mp3 --json beats.json   # BPM、拍点、重拍、高潮候选、安静/响亮段
python3 scripts/beat_timeline.py song.mp3 --film-dur 30 --key 12 --out timeline.json
```

- `--key` 是片子里最重要那一刻（揭晓、反转、logo）的秒数。脚本算出**歌从第几秒开始放 = 高潮在歌里的时刻 − key**，给出裁歌命令，再按拍点排好镜头：安静段每小节一刀，响亮段每拍一刀（字多的段落加 `--loud-every 2`）。`timeline.json` 交给画面那边排镜头。
- **测配乐本身，不测带音效的混音**。大段 riser、冲击会把高潮候选拽偏。实测 15 秒示例：纯配乐分轨的高潮 3.750s / 13.124s 和小节线完全重合，混了 riser 的成曲把第一高潮报成了 2.46s。
- 自己用 `arrange.py` 编的曲子不用测：小节网格就是 plan 里的 `bpm`，比任何检测都准。
- 自动拍点可能整体偏一两拍，以高潮候选（低频能量跳升点）为准。四拍底鼓的电子乐，脚本按最强高潮定小节第 1 拍。
- 片尾收在一个乐句的结尾，最后 1–2 秒淡出，别突然断掉。

## 用户点名的歌是硬要求

给了文件就用这个文件；只给了歌名，先找官方或授权来源。不许换成风格相近的曲子，也不许用代码合成一段「类似的」顶替。实在拿不到，交付时写明原因和替代品。用户说「不要配乐」，句与句之间就是真静音，不垫底噪。

## HeyGen 曲库：做试听

```bash
python3 scripts/heygen_audio.py search "sober cinematic wuxia, guzheng, sparse" --type music --limit 6
python3 scripts/heygen_audio.py fetch <id> -o m1.wav
```

- 描述写得越具体越好（乐器 + 情绪 + 场景），英文效果更好。
- 曲子多是 30s / 52s / 70s 定长。和视频长度差几秒时，用 `atempo` 微调速度（0.95–1.05 之间，音调不变）。差得多就剪段落，再加淡出。
- 拿不准风格时，挑 3 首 HeyGen 候选，再加 1 首 GarageBand 候选，每段截 9 秒（加 0.4s 淡入、0.7s 淡出），中间隔 0.8s 静音，拼成一个试听文件让用户挑。

## 版权（未查证，交付前提醒用户自行确认）

- Apple Loops：Apple 的许可一般允许用在自己创作的音乐和视频里，但不允许把 loop 本身单独再分发。
- HeyGen 素材：按 HeyGen 平台条款，下载到平台外使用前要确认。
- 代码合成：完全归自己所有。
