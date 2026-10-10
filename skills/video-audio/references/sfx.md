# 音效

**先找真实录音，库里没有才合成。** 模型合成的 riser、808、叮、whoosh 听多了都一个味道；曲库里的真实录音（真的鼓、真的门、真的纸）每次都能挑出不一样的。也别每条片子都塞「上升 + 冲击 + 叮」：音效跟着画面里发生的事走，画面里是翻书就用翻书声，是回车就用回车声。

## 密度档位

**默认「标准」：每个切点、每个关键帧都有声音。** 画面切了、东西落下了，声音没反应，观众会觉得「哑」。

| 档位 | 放在哪里 | 适合 |
|---|---|---|
| 标准（默认，30s 约 12–18 处） | 每个切点一个转场音效 + 每个关键动作一个命中音效（落下、揭晓、盖章、开灯、勾选） | 产品介绍、讲解、宣传片 |
| 丰富（30s 约 25–30 处） | 再加卡片落下、打字、关键词提示音 | 抖音、小红书节奏快的内容 |
| 克制（30s 约 6–8 处） | 只放大转场和结尾 | 用户要求安静，或者冥想、纪录片 |

转场音效按风格挑，别全片一种：嗖（快切）、翻页 / 纸张（手作、绘本）、快门 / 胶片咔哒（影像、复古）、低频轰（爆发段）。关键词提示音要比主音效轻（低 6–8 dB）；离其他音效不到 0.3s 的就跳过，否则会糊成一团。音效都写进 `mix.json` 的 `sfx`，`hit` 填画面上命中的时刻。

## 对齐

**开始时刻 = 命中时刻 − 峰值位置。** 「命中时刻」取画面动作完成的那一帧，不是动画开始的那一帧。比如盖章用 power4.in 从 3.98s 落到 4.33s，命中时刻就是 4.33s。

同一时刻最多叠两种音效。音效只放在「事件」上：落地、碰撞、切换、打字、碎裂、大字砸下，不是每个动作都要。

微错开更自然：预备音（吸气、上滑）略早，撞击音对准命中帧，碎屑、回响略晚 1–3 帧。转场 whoosh 的峰值应该落在画面切换最快的那一刻（擦除过半、卡片滑到中途）。

## HeyGen 音效库

```bash
python3 scripts/heygen_audio.py search "airy whoosh transition"
python3 scripts/heygen_audio.py fetch <id> -o sfx/whoosh.mp3
```

`--min-score` 默认 0.7 太严，脚本默认改成 0.4。用过、效果可靠的搜索词：

| 用途 | 搜索词 | 备注 |
|---|---|---|
| 转场 | `airy whoosh transition`、`card slide swoosh` | 1–1.5s，峰值约 0.2–0.45s |
| 爆点 / 揭晓 | `deep cinematic boom impact`、`heavy synthetic impact` | 带一点前置反向扫音的效果更好 |
| 盖章 / 落下 | `heavy stamp thud` | 峰值约 0.06s，几乎立刻命中 |
| 打字 | `typewriter typing keys` | 选 2s 左右的短版本，按需截取 |
| 锁定 / 确认 | `lock click metallic` | 0.26s 短促咔哒 |
| 上升 | `reverse cymbal swell build up` | 「Rumbling whoosh riser」峰值 2.52s |
| 氛围钟声 | `soft glass chime shimmer` | 「Ethereal metallic chime」先渐强再响，适合提前铺 |
| 中式点缀 | `bamboo wood knock`、`hollow clack` | 适合当关键词提示音，比电子提示音更有武侠味 |

## 代码合成（最后手段）

只在库里确实找不到、而且是很短的功能性音效时用。合成过的声音别当成每条片子的固定配方，品牌叮也不是每次都要。

```bash
python3 scripts/synth.py riser  --sec 2.8 -o riser.wav    # 峰值在末尾
python3 scripts/synth.py sub    -o sub.wav                # 808 下坠，叠在爆点
python3 scripts/synth.py ding   -o ding.wav               # 品牌收尾
python3 scripts/synth.py whoosh --sec 0.8 -o whoosh.wav   # 峰值在中点
python3 scripts/synth.py tick   -o tick.wav               # 关键词提示音
```

- 固定种子，同样参数输出完全一样。品牌叮声定下来后就当资产复用。
- 要新声音时往 `synth.py` 的 `KINDS` 里加一个函数：返回（波形，峰值秒数）。
- 代码合成适合短的、结构简单的声音。音色复杂的（真实撞击、环境声）还是从库里找。

## 其他本地来源

[uisfx](https://uisfx.com) 的 npm 包自带 12 套 UI 音效（arcade、cinematic、glass、zen……），每套约 70 个语义化事件声（check、lock、swipe、success……）。代码是 MIT 许可，音频是 CC0，可以直接从 `node_modules/uisfx/sounds/<pack>/<cue>.mp3` 取，适合产品演示里的点击、确认类声音。
