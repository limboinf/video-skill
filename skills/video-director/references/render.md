# 渲染：seek(t) 逐帧确定性渲染

默认路线：模型直接写一个网页，定义 `window.seek(t)`，`render.mjs` 用无头 Chrome 逐帧调用它、截图，再用 ffmpeg 编码成 mp4。没有视频框架，代码全在你手里。

## 1. 准备

```bash
mkdir my-film && cd my-film
npm i playwright-core                                  # 只装库，用系统 Chrome，不下载浏览器
cp <video-director>/templates/engine.html index.html   # 精密克制 / 电影慢镜 / 流体有机：改用 shader.html
cp <video-director>/templates/lib.js .            # 工具库，engine.html 引用它
node <video-director>/scripts/render.mjs index.html --out out --stills 0.5   # 先确认能出第一帧
```

- 竖版改模板 `:root` 的 `--W: 1080; --H: 1920;`，渲染时 `--w 1080 --h 1920`。两边不一致，`render.mjs` 会报警告。
- 浏览器直接打开 `index.html` 就是预览：自动缩放循环播放，空格暂停，← → 逐帧。
- 沙盒禁止本地端口时 `render.mjs` 会提示，到沙盒外运行。

## 2. 引擎规矩（违反任何一条，返工就会牵一发动全身）

- **所有样式和绘制只由 t 算出来**。没有定时器、没有 CSS transition / animation、没有「上一帧的状态」。
- 资源全部加载完再设 `window.ready = true`：字体 `await document.fonts.ready`，图片 `await img.decode()`。
- 随机用 `mulberry32(seed)`，**在 seek 外面预先生成好**（比如 200 个粒子的位置），seek 里只读不改。
- 分镜时间表和事件表放在文件最前面：`const SHOTS = [{id: 's1', a: 0, b: 3.2}, …]`，时刻从 `timeline.json` 抄，`seek` 里先找当前镜头再画。
- 舞台固定成成片分辨率，所有坐标按它写，不要响应式。
- 中文字体先用系统字体（macOS：PingFang SC、Songti SC、Kaiti SC）。要毛笔字、手写体，下载 OFL 开源字体放进工作目录本地加载，不依赖网络字体。
- 用模板现成的函数：`seg()` 区间进度、`E.*` 缓动（`bezier()` 可以直接抄 CSS / AE 的曲线）、`spring()` 弹簧、`beat / drop / pop / travel` 动作、`flash / shake / punch` 冲击、`focusIn / defocus / wipe / drawOn / sheen / lightSweep / grain` 高级感原语、`ev()` 拍点、`cameraAt()` 相机、`splitWords / riseWords` 逐词升起。用法见 `motion.md`。
- 着色器（`shader.html`）只读 `u_t`，不累加、不读上一帧；canvas 要 `preserveDrawingBuffer: true`，截图才拿得到画面。
- 素材视频（`<video>`）也要按 t 定位：`video.currentTime = t - 起点`，等 `seeked` 事件再返回。

## 3. 渲染命令

```bash
R=<video-director>/scripts/render.mjs
node $R index.html --out out --stills 0.5,3,8,15,22,28            # 静帧拼图 out/stills/sheet.jpg，不出视频
node $R index.html --out out --dur 4                               # 开头 4 秒小样，看动起来的样子
node $R index.html --out out --fps 30 --workers 4 --audio mix.wav --name final.mp4   # 全片 + 音轨
node $R index.html --out out --from 12 --to 16                     # 只重渲这一段（帧缓存会复用）
node $R index.html --out out/第1遍 --layers 1                       # 分三遍做：只画第 1 层
```

- 中断后重跑会跳过已渲好的帧；页面或同目录的 js/css 变了，旧帧自动作废。只改了子目录里的素材，加 `--force`。
- `--sub 4 --shutter 180`：每帧 4 个子帧混合做运动模糊，快门 180° 是电影标准（曝光半帧）。精密克制、电影慢镜、流体有机的成片默认开；弹性卡通快动作多时用 `--shutter 360`（拖影更长）；机械硬切不开，或 `--shutter 90`。渲染时间 ×K，静帧自查阶段不用开。
- 音频以视频时长为准，短了补静音。混音、响度在 video-audio 里做好再传进来。
- 渲染日志末尾列出页面报错（异常、资源加载失败）。有报错先修，别交付。

## 4. 性能

- 1080p、30 帧，60 秒就是 1800 帧。单帧控制在 0.3 秒以内：大面积纹理预先画进离屏 canvas，每帧只贴图；粒子控制在几千以内。
- 帧图默认在 `out/frames.noindex/`，`.noindex` 结尾的文件夹 macOS 的 Spotlight 不会去索引。
- 在别人正在用的电脑上渲染：命令前加 `nice -n 19`，一次只跑一个重活，`--workers` 合计别超过 CPU 核数。

## 5. 常见坑

- **别和 `lib.js` 的全局名撞名**：`W`、`H`、`E`、`ROOT`、`LAYERS`、`EVENTS`、`GRID`、`GRAIN` 等已经声明过了，页面里再 `const LAYERS = …` 会直接语法报错。`render.mjs` 会立刻报出是哪个名字。
- 想在无头浏览器里看页面的预览模式（比如检查概念预览页的样片能不能播）：启动参数加 `--disable-blink-features=AutomationControlled`，否则 `navigator.webdriver` 为 true，模板会当成渲染模式，不启动预览循环。
- 缓动函数两端要精确返回 0 和 1（模板的 `ends()` 包过了），否则 `if (p > 0)` 这类判断会让元素提前冒出来。
- 被隐藏的父元素下，子元素用 `visibility: inherit`，别写死 `visible`。
- 每个图层写明 `z-index`。
- 相机缩放时测量文字宽度用 canvas 的 `measureText`，不要用 DOM 尺寸。
- 要录一段网页操作，也在无头浏览器里逐帧渲染，鼠标是页面里画出来的光标。不占用真实屏幕和鼠标，不申请录屏权限。

## 6. 三维和素材

- 真三维（沙盘、组装、物体转着看）：页面里用 Three.js，照样走 seek(t)。把 `three.module.js` 下载到工作目录本地加载（渲染不依赖网络），渲染器开 `preserveDrawingBuffer`：

  ```html
  <script type="module">
  import * as THREE from './three.module.js';
  const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('gl'), antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(W, H, false);
  const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(35, W / H, 0.1, 100);
  // …搭场景，材质、灯光在 seek 外面建好…
  window.seek = async (t) => {
    const a = lerp(-0.6, 0.4, E.silk(seg(t, 0.5, 4)));          // 绕轴移动，推完停住
    cam.position.set(Math.sin(a) * 6, 1.6, Math.cos(a) * 6); cam.lookAt(0, 0.8, 0);
    renderer.render(scene, cam);
  };
  await document.fonts.ready; await window.seek(0); window.ready = true;
  </script>
  ```
  不要用 `THREE.Clock`、`AnimationMixer.update(delta)` 这类按真实时间累加的东西；动画混合器要用就 `mixer.setTime(t)`。
- 点名 Blender：bpy 脚本渲图片序列，再用 ffmpeg 合成，自检照样跑 `video_qa.py`。
- 写实照片、真实人物：先生图或找授权素材，再用代码剪辑包装（推拉、视差、叠层）。生图时每张按分镜写好景别和角度，别全是同一个机位的中景。
- 产品宣传片：读项目代码找卖点，把产品真的跑起来截真界面，不画假界面。
