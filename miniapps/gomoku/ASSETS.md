# 五子棋的素材来源

**没有任何外部素材。** 仓库里没有图片、字体、音频文件,构建产物里也没有:

- 棋盘与棋子是 Canvas 2D 程序化绘制(木纹、棋子高光、最后一手标记),没有图片;
- 音效:全部由浏览器 WebAudio 现场合成(振荡器 + 包络,共用 `miniapps/shared/src/sfx.ts`),没有任何音频文件;BGM 为 0;
- 触感:走宿主提供的 HapticFeedback 触感 API,不在宿主里时静默;
- 字体:系统字体栈(苹方 / Noto Sans CJK / system-ui),不下载、不打包任何字体;
- 网络:运行时没有任何 `fetch` / `XMLHttpRequest` / 外部 CDN 请求;规则与存档都在本地算。

## 原创性

规则、界面、配色、文案都是为超级赞原创的;没有使用任何商业游戏的名称、素材、角色或界面。

## 怎么核对

```sh
# 1. 仓库里没有任何二进制素材(只应有 index.html / superz.json / dist / src / test)
find miniapps/gomoku -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.webp' \
  -o -name '*.mp3' -o -name '*.wav' -o -name '*.ogg' -o -name '*.m4a' -o -name '*.woff*' -o -name '*.ttf' \) \
  -not -path '*/dist/*'

# 2. 源码里没有外部请求 / 内联脚本 / eval
grep -rn 'http://\|https://\|fetch(\|XMLHttpRequest\|eval(' miniapps/gomoku/src miniapps/gomoku/index.html

# 3. 构建产物只有 index.html、superz.json、assets/*.js、assets/*.css
unzip -l miniapps/gomoku/dist/gomoku.zip
```
