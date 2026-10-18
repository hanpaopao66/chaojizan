# 方块原野的美术和音效来源(1.1.0)

**全部由代码即时生成,没有任何外部素材、字体、图片或音频文件,也没有任何网络请求。**

| 内容 | 在哪儿 | 怎么来的 |
|---|---|---|
| 方块纹理(16×16,每面 3 个变体) | `src/textures.ts` | 用固定 salt 的整数哈希画草(草丛/小花)、土(石子)、石(裂纹)、沙(风纹)、树皮年轮、木板(板缝/木节)、玻璃(边框/反光)、砖缝、基岩;每个面生成 3 个变体,渲染时按方块坐标选一个,大片同种方块不会像壁纸一样重复 |
| 挖掘裂纹 | `src/textures.ts` | 4 个阶段的裂纹贴图,由固定种子的随机折线生成,按挖掘进度盖在目标方块面上 |
| 快捷栏图标 | `src/icons.ts` | 把侧面纹理的变体 0 画进 16×16 canvas,再 `toDataURL()` 成内联 `data:` URL(CSP 的 `img-src 'self' data: blob:` 允许) |
| 天空、云、星星、太阳/月亮 | `src/sky.ts` | 逐行算天空渐变(昼夜/日出日落暖色);云和星星是 64×32 的固定种子平滑随机场,按方位角+仰角取样,转头会跟着动;太阳/月亮按世界时间投影成圆盘 + 光晕 |
| 地形画面 | `src/render.ts` | Canvas 2D 的 DDA 光线投射;距离雾、面的明暗、水面波纹+天光反射、目标方块描边都是代码计算 |
| 碎屑粒子 | `src/particles.ts` | 挖/破方块时按方块尘土色生成几颗小方块,重力 + 淡出,投影到屏幕上 |
| 菜单装饰 | `src/style.css` | 纯 CSS 渐变画的天、云、山丘和弹层;没有任何 SVG/PNG |
| 音效 | `src/audio.ts` | WebAudio 现场合成:方波/正弦/三角波 + 白噪声经过带通滤波。挖/破/放/脚步按材质(草、土、石、沙、木、树叶、玻璃、砖、水)换音色;水下整条母线过 620 Hz 低通 |
| 环境声 | `src/audio.ts` | 白天是合成的鸟鸣(短促上滑音)、夜里是虫鸣(高频短脉冲),风是一直循环的白噪声 + 带通滤波,音量压得很低 |
| 字体 | 系统字体 | CSS 里只用系统字体栈(PingFang SC / Noto Sans CJK SC / system-ui),不下载字体 |

## 原创性

- 游戏名「方块原野」、规则、界面、方块种类和数值、成就、程序化纹理、天空/云/星星、碎屑和全部音效都是为超级赞原创的;
- 没有使用任何商业游戏(包括最有名的那款方块沙盒)的名称、素材、界面、音效和角色;
- 构建产物里只有 `index.html`、`superz.json` 和打包后的 JS/CSS,没有任何图片、音频、字体或第三方库文件。

## 怎么核对

```sh
# 1. 仓库里没有任何二进制素材(只应有 index.html / superz.json / dist / src / test)
find miniapps/sandbox -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.webp' \
  -o -name '*.mp3' -o -name '*.wav' -o -name '*.ogg' -o -name '*.m4a' -o -name '*.woff*' -o -name '*.ttf' \) \
  -not -path '*/dist/*'

# 2. 源码里没有外部请求
grep -rn 'http://\|https://\|fetch(\|XMLHttpRequest\|new Image()' miniapps/sandbox/src

# 3. 生产构建里没有调试钩子
node miniapps/scripts/check_miniapp_meta.mjs sandbox
```

构建产物同样只有 `index.html`、`superz.json`、`assets/*.js`、`assets/*.css`(见 `miniapps/sandbox/dist/pkg`)。
