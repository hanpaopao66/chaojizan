# Super-Z 官网(React + Three.js)

叙述平缓的单页官网:炉火余烬 3D hero(react-three-fiber)+ 滚动渐现叙事 +
实时信任数据(/stats/overview,与公开账本同源)。

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

- 品牌色与 App 一致:炉火橙 #FF5A1F / 账目绿 / 促销琥珀(见 docs/BRAND.md)
- 动画平缓:入场 0.9s 位移+淡入;余烬粒子慢速旋转上浮;
  全部动画尊重 `prefers-reduced-motion`
- 不喊口号:页面上的每个数字都来自公开接口,可点进原始数据
