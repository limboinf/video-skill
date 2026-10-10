// seek(t) 工具库：缓动、弹簧、动作函数、事件、相机、逐词升起，以及字幕、图片、波形这些通用件。
// 移植自 chuspeeism/code-video-director 的 engine.html（MIT），见仓库 NOTICE.md。复制到工作目录和 index.html 放在一起。
/* =================== 1. 工具函数（一般不用改） =================== */
const ROOT = getComputedStyle(document.documentElement);
const W = Number(ROOT.getPropertyValue('--W')) || 1920, H = Number(ROOT.getPropertyValue('--H')) || 1080;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, p) => a + (b - a) * p;
const seg = (t, a, b) => clamp((t - a) / (b - a));            // t 在 [a,b] 区间里的进度 0–1
const ends = (f) => (x) => (x <= 0 ? 0 : x >= 1 ? 1 : f(x));   // 缓动两端精确返回 0 和 1
const E = {
  linear: ends((x) => x),
  inOutCubic: ends((x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)),
  outCubic: ends((x) => 1 - Math.pow(1 - x, 3)),
  outQuart: ends((x) => 1 - Math.pow(1 - x, 4)),             // 先快后慢（抢拍：前两帧走完七成）
  inCubic: ends((x) => x * x * x),                            // 先慢后快、终点最快、到点急停：砸下、落地、离场用
  inQuad: ends((x) => x * x),
  outQuint: ends((x) => 1 - Math.pow(1 - x, 5)),
  outBack: ends((x) => 1 + 2.70158 * Math.pow(x - 1, 3) + 1.70158 * Math.pow(x - 1, 2)),
  outExpo: ends((x) => 1 - Math.pow(2, -10 * x)),
};
// 闭式阻尼弹簧（阶跃响应）：tau 是距起点的秒数，f 频率（Hz），z 阻尼比（<1 会回弹）。tau<=0 时为 0，最终趋于 1。
function spring(tau, f = 3, z = 0.6) {
  if (tau <= 0) return 0;
  const w = 2 * Math.PI * f;
  if (z >= 1) return 1 - Math.exp(-w * tau) * (1 + w * tau);
  const wd = w * Math.sqrt(1 - z * z);
  return 1 - Math.exp(-z * w * tau) * (Math.cos(wd * tau) + ((z * w) / wd) * Math.sin(wd * tau));
}
// 多目标弹簧求和：keys = [[t0, v0], [t1, v1], ...]，每换一次目标叠加一段弹簧，速度连续不跳变
function springTo(t, keys, f = 3, z = 0.6) {
  let v = keys[0][1];
  for (let i = 1; i < keys.length; i++) v += (keys[i][1] - keys[i - 1][1]) * spring(t - keys[i][0], f, z);
  return v;
}
// ===== Opus 5.5 的运动词汇（参数取自 Opus 5.5 代码里的原值，按动作类型挑，不要所有动作一个写法） =====
// bump：落定后的阻尼振荡——冲过头再来回弹两三下、越弹越小。amp 幅度（3%–10%），f 频率（2.4–3.2 赫兹），k 衰减（5.5–9 /秒）
const bump = (dt, amp, f = 2.6, k = 7) => (dt <= 0 ? 0 : amp * Math.exp(-k * dt) * Math.sin(2 * Math.PI * f * dt));
// squash：落地那一帧压扁 amount（5%–16%），按 0.05 秒指数弹回（两三帧）。用法：sy = 1 - squash(t - hit)，sx = 1 + 0.5 * squash(t - hit)
const squash = (dt, amount = 0.1, tau = 0.05) => (dt < 0 ? 0 : amount * Math.exp(-dt / tau));
// beat：入场四拍——预备 pre 秒先反向退 back → 主动作 dur 秒先快后慢 → 冲过头 over、弹两三下稳住。返回进度（会短暂 <0、>1）
function beat(t, start, { pre = 0.1, dur = 0.3, back = 0.05, over = 0.08, f = 2.6, k = 7 } = {}) {
  const t1 = start + pre, t2 = t1 + dur;
  if (t < start) return 0;
  if (t < t1) return -back * E.outCubic(seg(t, start, t1));
  if (t < t2) return -back + (1 + back) * E.outCubic(seg(t, t1, t2));
  return 1 + bump(t - t2, over, f, k);
}
// drop：砸下——fall 秒（3–4 帧）先慢后快砸到位，终点最快、到点急停，落地后回弹。配 squash(t - (start + fall)) 和冲击三件套
function drop(t, start, { fall = 0.12, over = 0.06, f = 2.4, k = 9 } = {}) {
  const hit = start + fall;
  if (t < start) return 0;
  if (t < hit) return E.inCubic(seg(t, start, hit));
  return 1 - bump(t - hit, over, f, k);
}
// 冲击三件套（砸下、出拳、亮相那一刻）：白闪 1–3 帧 + 震屏 3–8 帧 + 镜头顿推
const flash = (t, hit, dur = 0.08) => { const u = (t - hit) / dur; return u < 0 || u > 1 ? 0 : 1 - u; };          // 白色叠层的透明度
const shake = (t, hit, px = 14, dur = 0.25, fps = 30) => { const u = (t - hit) / dur; if (u < 0 || u > 1) return 0;
  return px * (1 - u) * (1 - u) * (Math.round((t - hit) * fps) % 2 ? -1 : 1); };                                     // 隔帧反向、平方衰减
const punch = (t, hit, amp = 0.05, dur = 0.2) => { const u = (t - hit) / dur; return u < 0 || u > 1 ? 0 : amp * (1 - u) * (1 - u); }; // 镜头推近 4%–10% 再回
// 镜头：两拍之间匀速慢推（Opus 的写法：慢推一律匀速，两头速度为零的缓动会让画面「定格」）；转场用甩镜头
const push = (t, a, b, s0 = 1, s1 = 1.04) => lerp(s0, s1, seg(t, a, b));                     // a→b 秒匀速从 s0 推到 s1
const whip = (t, at, dur = 0.14, dist = 1400) => { const u = (t - at) / dur; return u < 0 || u > 1 ? 0 : dist * E.inOutCubic(u); }; // 甩镜头：0.14 秒横移，配方向模糊
// 用法速查（时长要有长有短）：砸下 drop 0.1–0.13 秒｜入场 beat 0.3 秒｜轻的小东西 pop 0.2–0.3 秒｜大东西走位 travel 0.5–0.7 秒｜镜头慢推匀速或 punch
// 一组东西错开 1–2 帧（after 的 gap 0.03–0.06）；同一个东西的大小比位置晚 0.06 秒、旋转再晚一点；原地晃只留 1–3 像素

// ===== 按事件写，不按周期写（Opus 5.5 魔塔原片的写法）：每件事钉在一个拍点上、只发生一次 =====
// 拍点网格：bpm、offset（第 1 小节第 1 拍在片中第几秒）、每小节几拍，按 beats.py / beat_timeline.py 的结果改这一行
const GRID = { bpm: 120, offset: 0, bar: 4 };
const ev = (bar, b = 1) => GRID.offset + ((bar - 1) * GRID.bar + (b - 1)) * 60 / GRID.bpm;   // ev(27, 2) = 第 27 小节第 2 拍；半拍写 ev(28, 1.5)
// 逐帧关键帧表：把关键动作每一帧的进度写死，加速度就是你写出来的。Opus 挥剑：[0, .08, .18, .3, .62, 1]——前 3 帧慢慢蓄力、后 2 帧猛挥到位
const perFrame = (t, start, arr, fps = 30) => { const u = (t - start) * fps; if (u <= 0) return arr[0];
  if (u >= arr.length - 1) return arr[arr.length - 1]; const i = Math.floor(u); return lerp(arr[i], arr[i + 1], u - i); };
// 逐级加码：同一类冲击第 i 次（共 n 次）从 a 加到 b。Opus 一连几次重击：震屏 24 → 34 → 40 → 56 像素、红蓝错位 8 → 10 → 14 → 16
const ramp = (i, a, b, n) => lerp(a, b, n > 1 ? i / (n - 1) : 1);
// 高潮写成事件表，例：const HITS = [ev(27, 1), ev(27, 2), ev(28, 1), ev(28, 1.5)];   // 冲刺、双剑相交、反色、X 斩痕，各一次
//                   const sh = HITS.reduce((s, h, i) => s + shake(t, h, ramp(i, 24, 56, HITS.length)), 0);
// ===== 分步实现：三层骨架 + 共用事件表（第一遍主动作 → 第二遍辅层 → 第三遍冲击，每遍量过就锁住，见 references/motion.md 第 6 节） =====
// 页面按 ?layers=1,2 只画这几层（render.mjs --layers 1,2）；不带参数就三层全开。三层分文件写（比如 main.js、aux.js、impact.js），锁层按文件锁。
const LAYERS = new Set((new URLSearchParams(location.search).get('layers') || '1,2,3').split(',').map(Number));
// 共用事件表：第一遍定下来、锁住。at 哪一刻（用 ev() 写拍点）、kind 什么事、hit 是不是重击（第三遍只给 hit 的事件加冲击）、x/y 发生在哪、power 多重（冲击逐级加码用）
const EVENTS = [
  // { at: ev(3, 1), kind: '变身', hit: true, x: 960, y: 540, power: 1 },
];
const hits = (t, win = 0.6) => EVENTS.filter((e) => e.hit && t >= e.at && t < e.at + win);   // 冲击层取用：刚发生的重击
// 画的时候按层：if (LAYERS.has(1)) drawMain(t); if (LAYERS.has(2)) drawAux(t); if (LAYERS.has(3)) drawImpact(t);
// 镜头也分层：缓推、跟摇属于辅层（第二遍），顿推、震屏属于冲击层（第三遍）——cam.s = push(...) * (1 + (LAYERS.has(3) ? punch(...) : 0))
// 冲击叠层（Opus 5.5 重击的写法）：同一帧爆开白闪 flash()、震屏 shake()、顿推 punch()、拟声大字 sfx()、一圈碎片火花 burst()、速度线。
// 主动作只要三四帧，画面的热闹来自这些同时炸开、各自飞走的伴奏层——快和热闹不打架。
// burst：一圈碎片 / 火花从 (x, y) 炸开、先快后慢飞远并下落；返回每片 [x, y, 大小, 透明度]，自己画成方块、火花线或纸屑
function burst(t, hit, x, y, { n = 24, dist = 360, size = 14, life = 0.45, grav = 900, seed = 1 } = {}) {
  const dt = t - hit; if (dt < 0 || dt > life) return [];
  const r = mulberry32(seed), k = E.outQuart(dt / life), out = [];
  for (let i = 0; i < n; i++) {
    const a = r() * Math.PI * 2, d = dist * (0.4 + 0.6 * r()), s = size * (0.5 + r());
    out.push([x + Math.cos(a) * d * k, y + Math.sin(a) * d * k + 0.5 * grav * dt * dt, s * (1 - 0.5 * dt / life), 1 - dt / life]);
  }
  return out;
}
// sfx：拟声大字（「锵！」「斩！」「轰！」）砸进来 0.1 秒（从 1.6 倍缩回、带一点旋转），停 0.35 秒，0.15 秒淡出；返回 {s, rot, a}，自己画（粗描边 + 填色）
const sfx = (t, hit, { inDur = 0.1, hold = 0.35, out = 0.15, rot = -0.12 } = {}) => {
  const dt = t - hit; if (dt < 0 || dt > inDur + hold + out) return null;
  const p = E.outBack(Math.min(1, dt / inDur));
  return { s: lerp(1.6, 1, p), rot: rot * (1 - 0.3 * p), a: dt < inDur + hold ? 1 : 1 - (dt - inDur - hold) / out };
};
// 辅层（《七层动效手册》的主辅分工）：每个镜头 1 个快主动作 + 至少 3 层辅动作。辅动作小幅、小面积、可以循环、不抢注意力；主动作必须是一次性的事件。
// 安静镜头（对话、分食、包扎）最容易空：镜头匀速缓推 push() + 一层真的在走的粒子 drift() + 一两样小东西小摆 sway()，三层托住画面。
// sway：小东西原地小摆（烛火、斗篷角、旗子、叶子），幅度 1–3 像素或 1–3 度，周期 1.2–3.4 秒；每样 phase 错开，别整排一起晃
const sway = (t, amp = 2, period = 2.2, phase = 0) => amp * Math.sin(2 * Math.PI * (t / period + phase));
// drift：第 i 颗粒子真的在走（飘落的灰 speed>0、上升的火星 speed<0、雨丝），匀速穿过 dist 像素再从头来，各颗起点不同；返回 [x, y]
function drift(t, i, { x0 = 0, y0 = 0, w = W, dist = H, speed = 60, wob = 6, seed = 3 } = {}) {
  const r = mulberry32(seed + i * 7919), x = x0 + r() * w, off = r() * dist;
  return [x + wob * Math.sin(t * 0.8 + i), y0 + (((off + t * speed) % dist) + dist) % dist];
}
// 别写 const q = t % 0.78; slash(q)——那是同一刀每拍重播一遍。t % 周期 只许用在眨眼、冒汗、火星、速度线闪动、滚动背景这类背景小效果。

// ===== 动作的三个现成写法（不要用 inOutCubic 做物体动作，更不要用 linear） =====
// 走位：从 a 到 b，默认 0.4 秒、快起慢停。要冲过头再回来就用 ease: E.outBack。一个动作 0.25–0.5 秒做完。
const travel = (t, start, a, b, { dur = 0.4, ease = E.outQuart } = {}) => lerp(a, b, ease(seg(t, start, start + dur)));
// 弹出：0 → 1 带一点过冲，出现、放大、落位都用它（0.3–0.4 秒）
const pop = (t, start, dur = 0.35) => E.outBack(seg(t, start, start + dur));
// 依次：一串元素第 i 个晚 gap 秒开始（gap 0.04–0.1），用来做「一串小东西依次飞入、拼装」
const after = (t, start, i, gap = 0.06) => t - (start + i * gap);
// 带种子的随机数：同一种子每次结果一样，保证任意跳帧画面一致（不要用 Math.random）
function mulberry32(a) {
  return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
// 把元素里的文字拆成「遮罩 + 内层」：data-split="word" 按空格分词，"char" 逐字；保留 <br> 和 <em> 等内联标签
function splitWords(el) {
  const mode = el.dataset.split || 'word', gap = el.dataset.gap ?? (mode === 'char' ? '0' : '.25em'), out = [];
  const walk = (node) => {
    for (const n of [...node.childNodes]) {
      if (n.nodeType === 3) {
        const parts = mode === 'char' ? [...n.textContent.replace(/\s+/g, '')] : n.textContent.split(/\s+/).filter(Boolean);
        const frag = document.createDocumentFragment();
        for (const p of parts) {
          const w = document.createElement('span'), wi = document.createElement('span');
          w.className = 'w'; w.style.marginRight = gap; wi.className = 'wi'; wi.textContent = p;
          w.appendChild(wi); frag.appendChild(w); out.push(wi);
        }
        n.replaceWith(frag);
      } else if (n.nodeType === 1 && n.tagName !== 'BR') walk(n);
    }
  };
  walk(el);
  return out;
}
// 按词遮罩升起：第 k 个词在 start + k*stagger 开始，用 dur 秒从遮罩下方升到原位
function riseWords(words, t, start, { stagger = 0.06, dur = 0.55, ease = E.outExpo, from = 110, tilt = 4 } = {}) {
  words.forEach((w, k) => {
    const p = ease(seg(t, start + k * stagger, start + k * stagger + dur));
    w.style.transform = `translateY(${(1 - p) * from}%) rotate(${(1 - p) * tilt}deg)`;
  });
}
// 相机：关键帧 {t, x, y, s, r, ease}，(x,y) 是画面中心对准的世界坐标；位置和缩放都按缓动插值（缩放取对数，推拉才均匀）。
// 镜头推完要停：相邻两个关键帧写同一个值就是「停住」。不要一个镜头从头推到尾——让动作在静止的镜头里发生。
function cameraAt(t, keys, ease = E.inOutCubic) {
  if (t <= keys[0].t) return { r: 0, ...keys[0] };
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1], b = keys[i];
    if (t > b.t) continue;
    const p = (b.ease || ease)(seg(t, a.t, b.t));
    return { x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p), s: Math.exp(lerp(Math.log(a.s), Math.log(b.s), p)), r: lerp(a.r || 0, b.r || 0, p) };
  }
  return { r: 0, ...keys[keys.length - 1] };
}
const mixCam = (c, k) => ({ x: lerp(W / 2, c.x, k), y: lerp(H / 2, c.y, k), s: Math.exp(Math.log(c.s) * k), r: (c.r || 0) * k }); // k<1 做视差
const cssCamera = (el, c) => { el.style.transform = `translate(${W / 2}px,${H / 2}px) rotate(${c.r || 0}deg) scale(${c.s}) translate(${-c.x}px,${-c.y}px)`; };
const ctxCamera = (ctx, c) => { ctx.setTransform(1, 0, 0, 1, W / 2, H / 2); ctx.rotate(((c.r || 0) * Math.PI) / 180); ctx.scale(c.s, c.s); ctx.translate(-c.x, -c.y); };
const fade = (el, p, dy = 14) => { el.style.opacity = p; el.style.transform = `translateY(${(1 - p) * dy}px)`; };


/* =================== 通用件（和风格无关，每条片子都用得上） =================== */
// 图片按「铺满裁切」画进一个框（像 CSS object-fit: cover），filter 可做调色：'sepia(.8) saturate(.6)'
function coverImage(ctx, img, x, y, w, h, filter = 'none') {
  const r = Math.max(w / img.naturalWidth, h / img.naturalHeight), sw = w / r, sh = h / r;
  ctx.save(); ctx.filter = filter;
  ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, x, y, w, h); ctx.restore();
}
// 配音波形：film_data.py 导出的 VOWAVE，取第 t 秒的峰值（0–1）
const peakAt = (wave, t) => { const i = Math.floor(t * wave.rate); return i >= 0 && i < wave.peaks.length ? wave.peaks[i] : 0; };
// 当前这一刻该显示哪条字幕（cues 来自 voiceover.py align）：显示到下一条开始，最后一条多留 lead 秒
function cueAt(cues, t, { lead = 0.08, tail = 0.6 } = {}) {
  for (let k = 0; k < cues.length; k++) {
    const a = cues[k].start - lead, b = cues[k + 1] ? cues[k + 1].start - lead : cues[k].end + tail;
    if (t >= a && t < b) return { cue: cues[k], k, p: seg(t, a, a + 0.14) };
  }
  return null;
}
// Canvas 字幕：底部居中，按空格断行，最多两行，底部压暗一条保证任何画面上都读得清
function drawSubtitle(ctx, cues, t, { font = 'bold 54px "PingFang SC", sans-serif', color = '#fff', y = H - 180, maxW = W - 180,
  band = 'rgba(0,0,0,.8)', lineH = 70 } = {}) {
  const c = cueAt(cues, t); if (!c) return;
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  if (band) { const g = ctx.createLinearGradient(0, y - 200, 0, H); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(0.45, band); g.addColorStop(1, band);
    ctx.fillStyle = g; ctx.fillRect(0, y - 200, W, H - y + 200); }
  ctx.font = font; ctx.textAlign = 'center'; ctx.fillStyle = color; ctx.globalAlpha = E.outCubic(c.p);
  ctx.shadowColor = 'rgba(0,0,0,.7)'; ctx.shadowBlur = 10;
  const lines = []; let cur = '';
  for (const w of c.cue.text.split(' ')) { const nx = cur ? cur + ' ' + w : w; if (ctx.measureText(nx).width > maxW && cur) { lines.push(cur); cur = w; } else cur = nx; }
  lines.push(cur);
  lines.slice(-2).forEach((l, i, arr) => ctx.fillText(l, W / 2, y - (arr.length - 1 - i) * lineH));
  ctx.restore();
}
