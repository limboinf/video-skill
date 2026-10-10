# 配音

## 选声音来源

| `--source` | 是什么 | 什么时候用 | `--voice` 填什么 |
|---|---|---|---|
| `mine`（默认） | 你在 HeyGen 复刻的声音 | 用户说「用我的声音」，或者没说 | 不填就用第一个复刻声音 |
| `heygen` | HeyGen 公共声音库 | 不用自己的声音，又想要 HeyGen 的中文播音腔 | `voices --source heygen --language Chinese` 查到的 voice_id |
| `gemini` | Gemini 3.8 Flash TTS | 不用自己的声音，要自然的口语语气、要用一句话控制语气 | 声音名：`Puck`（活泼）、`Kore`（干脆）、`Charon`（讲述）、`Sulafat`（温暖）、`Achird`（友好）……`voices --source gemini` 列全 |

三种来源用同一份稿子、同一种停顿写法，输出都是 48kHz 单声道 WAV，后面的 `align`、混音不用管声音从哪来。

```bash
python3 scripts/voiceover.py voices --source mine
python3 scripts/voiceover.py tts script.txt -o vo.wav                                   # 自己的声音
python3 scripts/voiceover.py tts script.txt -o vo.wav --source heygen --voice <voice_id>
python3 scripts/voiceover.py tts script.txt -o vo.wav --source gemini --voice Puck --style "轻松聊天，像跟朋友介绍自己的作品"
```

### Gemini 要注意的

- 密钥从环境变量 `GEMINI_API_KEY` 读，网络不通时设 `https_proxy`。密钥不写进代码、不打印。
- **语气只写在 `--style` 里**。Gemini 3.8 把正文当逐字台词，正文里写「开心地说：」会被念出来。语速也写在 style 里（「语速稍快」）。
- `<break time="0.3s"/>` 会自动换成 Gemini 的停顿标签：0.5s 以内是 `<short pause>`，更长是 `<long pause>`。实测 0.8s 的停顿生成了约 0.65s 的静音，停顿时长不如 HeyGen 精确，要卡点的句子用 `align` 看真实位置。
- 声音的性别、年龄、口音靠换声音，不写进 style。所有声音都能说中文，列表里的英文口音只是它的母语。
- 请求格式以实测为准：`POST /v1beta/interactions`，返回 `steps[].content[]` 里 base64 的 WAV（24kHz 单声道）。

## HeyGen 生成

- `tts` 会按 orca → starfish → elevenlabs 依次尝试。复刻声音不指定引擎时，常见报错是「saved voice engine is not available」。
- 实测同一段 130 字中文：orca 31.0s，starfish 35.3s。orca 语速更接近日常口播，优先用它。
- 停顿用 `<break time="0.3s"/>`，**必须写秒**，写毫秒 HeyGen 会报错。每句之间放 0.3s，句子之间的边界听起来更清楚，静音切段也更准。
- 中文口播大约每秒 4.2–4.5 字。30 秒视频的稿子控制在 130 字左右。
- 每句不超过 20 个字，一句就是一条字幕。句间 0.25–0.4s，段落之间 0.6–0.8s。
- 稿子里的英文专名（项目名、命令）会被中文模型读得别扭。能换中文说法就换；必须读英文时，单独听一遍这一句。

## 字幕时间对齐（不需要 whisper）

HeyGen 返回的 `word_timestamps` 是**按字平均分的**（每字固定 0.14s），和真实语速对不上，不能用。

稿子是自己写的，文字已知，缺的只是时间。所以不用语音识别，直接对齐：

```bash
python3 scripts/voiceover.py align script.txt vo.wav -o cues.json
```

1. 静音检测（-35dB、0.2s）切出真实说话段落。
2. 稿子按 `<break>` 分句、再按逗号句号切成分句，按字数算出每个分句边界大约落在第几秒。
3. 动态规划在段落之间的停顿里挑一组最贴近的位置当边界，所以每条字幕的起止都落在真实的换气上。
4. 同一句里相邻的分句，合起来不超过一行（16 个汉字宽）就并成一条，中间用空格隔开。

输出 `[{text, start, end}]`，字幕显示到下一条开始。停顿比分句还少时（引擎没停顿），它会退回到按整句对齐；整句都对不上就报错，在稿子里每句之间加 `<break time="0.3s"/>` 重新合成。

实测 30 秒介绍片：whisper（small）把整段识别成一个片段，还把「HeyGen」听成「黑镇」、「古筝」听成「古针」；`align` 出 11 条字幕，起止都落在换气处。whisper 只在要做逐字高亮这类比分句还细的时间时才用，作为可选项：`whisper vo.wav --model small --language zh --word_timestamps True --output_format json`。

### 字幕停多久

跟着配音念的字幕，起止等于这句话的真实起止，观众边听边读，每条至少 1.2s（`align` 会提醒太短的）。没配音的字（大字、无旁白字幕）才按「字数 × 0.25s + 0.5s」，见 video-director。

### 画面跟着配音走

- 说到哪个词，那个东西正好出现或被点亮。
- 换场景放在一句开口之前 0.1–0.2s，观众先看到画面再听到话，感觉更顺。
- 把每句的起止时间写进时间表，它就是全片的时间骨架，配乐和音效都往上挂。

### 要逐句精确时长时

整段合成一次再切段最省调用。要精确控制每句的位置（比如句子要卡在画面节拍点上），改成每句单独合成一个文件，用 `ffprobe` 量时长，再按时间表拼。代价是调用次数多，句与句之间语气可能不连贯，先试听一遍。

## 交付

- `vo.wav` 和它的时长（视频总长 = 配音时长 + 0.3–0.5s 收尾）
- 说话段落 JSON（字幕和音效排期都要用）
