# 突击时刻的素材来源

**没有任何外部素材。** 仓库里没有图片、字体、音频文件,构建产物里也没有:

- 两张地图(旧仓库 / 霓虹夜市)的地面纹理、墙、箱子/摊位、A/B 炸弹点、霓虹光晕,玩家/守卫
  (含走路摆动、枪口方向)、子弹曳光、弹壳、火花、烟、枪口火光、HUD 图标与比分点:
  全部由 `src/render.ts` / `src/hud.ts` / `src/screens.ts` 用 Canvas 2D 现场绘制(几何图形 + 程序化配色),没有图片文件;
- 首页两张地图的小预览图也是用 Canvas 2D 把同一份 ASCII 地图数据缩着画出来的;
- 音效:全部由 `src/audio.ts` 用 WebAudio 现场合成(振荡器、包络、程序生成的白噪声),
  枪声/换弹/切枪/脚步/安放/炸弹蜂鸣/爆炸/胜负/成就音都没有音频文件;带位置的音效走
  PannerNode 做空间化(左右与距离衰减);
- BGM:同样由 `src/audio.ts` 现场合成的循环(低频持续音 + 心跳脉冲),没有音乐文件;
- 字体:系统字体栈(苹方 / Noto Sans CJK / system-ui),不下载、不打包字体;
- 网络:运行时没有任何 `fetch` / `XMLHttpRequest` / 外部 CDN 请求;地图、AI、回合状态机、
  存档读写都在本地算。

## 原创性

- 两张地图都是 `src/map.ts` 里手写的 44×26 字符画(旧仓库 / 霓虹夜市),布局、掩体、A/B 点都是为本游戏画的;
- 玩家和守卫是抽象图形,没有人物肖像;命中的表现是火花/烟/弹壳,**没有血腥表现**;
- 没有使用《CS2 / 反恐精英》或任何其他商业射击游戏的名称、地图、武器、角色、界面或音效;
  不涉及任何真实武器品牌、真实地点或他人的素材;
- 标题「突击时刻」、规则、数值、AI、界面都是为超级赞原创的。

## 怎么核对

```sh
# 1. 仓库里没有任何二进制素材(只应有 index.html / superz.json / dist / src / test)
find miniapps/tactical -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.webp' \
  -o -name '*.mp3' -o -name '*.wav' -o -name '*.ogg' -o -name '*.m4a' -o -name '*.woff*' -o -name '*.ttf' \) \
  -not -path '*/dist/*'

# 2. 源码里没有外部请求 / 内联脚本 / eval
grep -rn 'http://\|https://\|fetch(\|XMLHttpRequest\|new Image()\|eval(' miniapps/tactical/src miniapps/tactical/index.html

# 3. 构建产物只有 index.html、superz.json、assets/*.js、assets/*.css
unzip -l miniapps/tactical/dist/tactical.zip
```

构建产物同样只有 `index.html`、`superz.json`、`assets/*.js`、`assets/*.css`
(见 `miniapps/tactical/dist/pkg`),没有图片、音频或字体文件。
