# Super-Z 官网(React)

首页(`src/Home.jsx`)讲聚合平台:服务台(频道开没开读 `/channels`)+ 一张费率表 +
实时账目(/stats/overview、/transparency/audit,与公开账本同源)。
入驻页、品牌页、大屏、透明中心是同一个包里的子路由。

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

- 首页颜色取 `packages/shared/lib/src/brand.dart` 产品层(骨白 / 黏土 / earn / hold /
  频道色槽),写在 `src/home.css` 顶部;子页仍是旧的深色版(`src/styles.css`)
- `styles.css` 是**全局**样式,首页的类名不能和它重名(`.brand` `.cta` `.btn` `.app` 等),
  否则那些规则会漏进首页。原因和实测现象见 `Home.jsx` 顶部注释
- 首页标题用的衬线字是子集:改了 h1 / h2 / 频道字块的文案要重跑
  `python3 scripts/gen_font_subset.py --web`(CI 的「显示字覆盖率」会拦漏跑)
- 不喊口号:页面上的每个数字都来自公开接口,可点进原始数据
