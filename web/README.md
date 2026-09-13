# Super-Z 官网(React)

首页(`src/Home.jsx`)讲聚合平台:服务台(频道开没开读 `/channels`)+ 一笔单子的
流程动画(`src/FlowFilm.jsx`)+ 一张费率表 + 实时账目(/stats/overview、
/transparency/audit,与公开账本同源)。
费率(`/rates`)、透明中心(`/transparency`)、商家入驻 / 骑手加入(`/join/*`)、
开源仓(`/opensource`)、频道页(`/channel/{key}`)、品牌页、大屏是同一个包里的子路由。

## 开发

```bash
cd web
npm install
npm run dev        # vite 开发服,/stats 等接口代理到 127.0.0.1:8010
```

## 构建与部署

```bash
npm run build      # 产物直接输出到 ../server/static/site/
```

构建产物随仓库提交,生产机**无需 node**:FastAPI 的 `/` 路由检测到
`static/site/index.html` 存在即托管新官网,不存在则退回老的单页 index.html。

## 设计约定

- 除大屏(`/screen`)外全站浅色,颜色取 `packages/shared/lib/src/brand.dart` 产品层
  (骨白 / 黏土 / earn / hold / 频道色槽)。公共令牌、顶栏页脚、按钮表格在 `src/site.css`,
  各子页的版式在 `src/pages.css`,首页自己的在 `src/home.css`。
  大屏是同一套令牌的深色态(`SzColors.dark`),挂在 `.screen-root` 上,在 `src/screen/screen.css`
- `styles.css` 只剩重置和深色底(大屏首屏不闪白),但它仍是**全局**样式 ——
  别往里加规则,否则会漏进浅色页。原因和实测现象见 `Home.jsx` 顶部注释
- 大屏的地图是平面 SVG,省界读 `src/films/chinaGeo.js`(`scripts/gen_site_geo.py` 生成,
  34 个省级行政区 + 南海诸岛附图);改了地图跑 `node scripts/verify_map.mjs`(要先 `npm run dev`)
- 动效和 App 同一套(令牌在 `packages/shared/lib/src/motion.dart`):分账条 900ms 生长、段间 120ms,
  数字 900ms 滚到终值,卡片 220ms 淡入;系统开了「减少动态效果」就直接给终态
- 标题用的衬线字是子集(全站 h1 / h2、频道字块、流程动画的字幕):改了这些文案要重跑
  `python3 scripts/gen_font_subset.py --web`(CI 的「显示字覆盖率」会拦漏跑)
- 不喊口号:页面上的每个数字都来自公开接口,可点进原始数据
