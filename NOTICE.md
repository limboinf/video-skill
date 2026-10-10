# 致谢与授权

- **chuspeeism/code-video-director**（MIT License，Copyright (c) 2026 chuspeeism）
  `skills/video-audio/scripts/beats.py`、`beat_timeline.py` 移植自该项目。改动：电子乐反拍踩镲导致拍点整体偏半拍时自动校正；有高潮时按最强高潮定小节第 1 拍。
  `audio_qa.py` 的检查项（静音、响度、真峰值、切点落拍）参考了它的 `qa.py`。
  `references/` 里的字幕停留时长、配音与画面对齐、用户点名即硬要求等规则，参考了它的 `references/05-声音.md` 和 `09-翻车清单.md`，用自己的话重写。
  `skills/video-director/scripts/render.mjs`、`templates/engine.html` 移植自它的同名文件，只改了注释和演示文字。
  `skills/video-director/scripts/video_qa.py` 的检查项和阈值（黑帧、冻帧、补漏切点、空底、版式雷同、每秒变化、联系表）移植自它的 `qa.py`，去掉了光流动态检查。
  `skills/video-director/references/` 的约束体系（导演单、节奏档、按动作类型定时长、按事件写、主辅分工、分三遍做、风格卡、评分表、翻车清单）参考了它的 `SKILL.md` 和 `references/01、02、06、07、08、09、11`，用自己的话重写，改成 GSAP 写法并和 HyperFrames 的 motion-doctrine 对齐。
- 上游的 `beats.py` 部分思路又来自 **howseen-ai/claude-motion-design**（MIT License，Copyright (c) 2026 Howseen AI / Raphaël Aubry）。

MIT 授权原文：Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
