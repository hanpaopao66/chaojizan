# 方块原野的美术和音效来源

**全部由代码即时生成,没有任何外部素材、字体、图片或音频文件,也没有任何网络请求。**

| 内容 | 在哪儿 | 怎么来的 |
|---|---|---|
| 方块纹理(16×16) | `src/textures.ts` | 每种方块顶/侧/底三个面,用固定 salt 的整数哈希画草、土、石、沙、树皮年轮、木板、玻璃、砖缝、基岩;渲染色号写死在这个文件里,不加载图片 |
| 快捷栏图标 | `src/icons.ts` | 把上面的侧面纹理画进 16×16 canvas,再 `toDataURL()` 成内联 `data:` URL(CSP 的 `img-src 'self' data: blob:` 允许) |
| 天空、太阳、月亮 | `src/render.ts` | 逐行算天空渐变;太阳/月亮按世界时间投影成圆盘 + 光晕,全部在低分辨率缓冲里直接写像素 |
| 地形画面 | `src/render.ts` | Canvas 2D 的 DDA 光线投射;距离雾、面的明暗、水面半透明、目标方块描边都是代码计算 |
| 菜单装饰 | `src/style.css` | 纯 CSS 渐变画的天、云、山丘;没有任何 SVG/PNG |
| 音效 | `src/audio.ts` | WebAudio 现场合成:方波/正弦/三角波 + 白噪声经过带通滤波,挖、放、跳、落地、菜单点击、挖不动等 |
| 字体 | 系统字体 | CSS 里只用系统字体栈(PingFang SC / Noto Sans CJK SC / system-ui),不下载字体 |

## 原创性

- 游戏名「方块原野」、规则、界面、方块种类和数值、程序化纹理和音效都是为超级赞原创的;
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
```

构建产物同样只有 `index.html`、`superz.json`、`assets/*.js`、`assets/*.css`(见 `miniapps/sandbox/dist/pkg`)。
