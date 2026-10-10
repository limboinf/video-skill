#!/usr/bin/env bash
# 15 秒动感短曲示例：GarageBand「Cascade」128 BPM + HeyGen 冲击/上升/低音轰 + 代码合成。
# 运行：bash make.sh   产出：out/mix.m4a 和三条分轨
set -euo pipefail
cd "$(dirname "$0")"
S=../../scripts
mkdir -p sfx

python3 $S/synth.py riser --sec 2.8 -o sfx/code_riser.wav
python3 $S/synth.py sub -o sfx/code_sub.wav
python3 $S/synth.py ding -o sfx/code_ding.wav

python3 $S/heygen_audio.py search "reverse cymbal swell build up" >/dev/null
python3 $S/heygen_audio.py search "deep cinematic boom impact" >/dev/null
python3 $S/heygen_audio.py fetch 1811c5a6dbe21418 -o sfx/heygen_impact.mp3
python3 $S/heygen_audio.py fetch b426f7cb850e09cf -o sfx/heygen_riser.mp3
python3 $S/heygen_audio.py fetch 7e1cbac754e4a9f7 -o sfx/heygen_boom.mp3

python3 $S/arrange.py plan.json
