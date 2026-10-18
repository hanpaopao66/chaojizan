# 贪吃蛇的素材来源

**没有任何外部素材。** 仓库里没有图片、字体、音频文件,构建产物里也没有:

- 画布是 Canvas 2D 程序化绘制(网格、蛇身、食物、粒子),没有图片;
- 音效:没有音效文件;少量反馈用 WebAudio 合成(如有关)。
- 字体:系统字体栈(苹方 / Noto Sans CJK / system-ui),不下载、不打包任何字体;
- 网络:运行时没有任何 `fetch` / `XMLHttpRequest` / 外部 CDN 请求;规则与存档都在本地算。

## 原创性

规则、界面、配色、文案都是为超级赞原创的;没有使用任何商业游戏的名称、素材、角色或界面。

## 怎么核对

```sh
# 1. 仓库里没有任何二进制素材(只应有 index.html / superz.json / dist / src / test)
find miniapps/snake -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.webp' \
  -o -name '*.mp3' -o -name '*.wav' -o -name '*.ogg' -o -name '*.m4a' -o -name '*.woff*' -o -name '*.ttf' \) \
  -not -path '*/dist/*'

# 2. 源码里没有外部请求 / 内联脚本 / eval
grep -rn 'http://\|https://\|fetch(\|XMLHttpRequest\|eval(' miniapps/snake/src miniapps/snake/index.html

# 3. 构建产物只有 index.html、superz.json、assets/*.js、assets/*.css
unzip -l miniapps/snake/dist/snake.zip
```
