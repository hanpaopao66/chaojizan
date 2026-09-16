# 快速开始

从零到上线,按这个顺序走一遍。前五步不需要认证,可以先跑起来再说。

## 1. 注册

打开开发者后台 [`/dev/`](/dev/),用手机号 + 验证码登录,第一次登录就是注册。

> 开发者注册**对所有人开放**,小程序、小游戏都一样,不用邀请。平台只在出问题时临时收紧或暂停注册,那时登录会看到原因。

## 2. 建应用

「我的应用 → 新建应用」:名称、类型(应用 / 小游戏)、分类、一句话介绍。

创建成功会弹出 **AppID 和 AppSecret**。AppSecret **只显示这一次**,立刻存到你的服务端配置里 ——
平台只存密文,丢了只能轮换(见[服务端 · 密钥轮换](server.md#密钥轮换))。

## 3. 下载模板

最小模板在开源仓 [`miniapps/_template/`](https://github.com/hanpaopao66/chaojizan/tree/main/miniapps/_template),三个文件:

```text
index.html     同源引 /_sdk/2/sz-webapp.js
app.js         展示 open_id、设置主按钮、把 initData 交给你的后端验签
superz.json    包清单
```

`superz.json`:

```json
{
  "sdk": "2",
  "kind": "app",
  "orientation": "portrait",
  "background_color": "#F0EEE6",
  "spa_fallback": false
}
```

- `kind` 要和建应用时选的类型一致(`app` / `game`);
- `orientation`:`portrait` / `landscape` / `any`(小游戏打开时按它锁方向);
- `background_color`:启动页和页面加载前的底色;
- `spa_fallback`:单页应用用前端路由时设 `true`,找不到的无扩展名路径回 `index.html`。

本地调试:任意静态服务器打开 `index.html?sz_mock=1`,SDK 进入 mock 模式 —— 弹窗用浏览器原生、
云存储落在 localStorage、initData 带 `mock=1` 且**签名必然无效**(你的后端验签会拒绝,这是故意的)。

## 4. 打包上传

```bash
cd miniapps/_template && zip -r ../hello.zip . -x README.md
```

后台「版本 → 上传开发版」,拖进 zip。平台逐条校验并给出报告:

- 根目录必须有 `index.html` 和 `superz.json`;
- 应用 ≤ 10 MB、小游戏 ≤ 30 MB(压缩后),单文件 ≤ 5 MB,最多 1000 个文件,解压后总共 ≤ 90 MB;
- 只收这些扩展名:html、js、mjs、css、json、txt、png、jpg、jpeg、gif、webp、svg、ico、woff、woff2、ttf、otf、mp3、ogg、wav、m4a、webm、mp4、wasm、map;
- 不能有符号链接、绝对路径、`..`、隐藏文件。

引用了外部脚本、样式的包能传,但报告里会有警告 —— 托管页的 CSP 只放行同源脚本,外部脚本加载不了。

## 5. 模拟器

后台「模拟器」页:选版本 → 启动。模拟器是一个完整的模拟宿主(和 App 网页版同一套协议),
initData **是真签名**的(`env=sim`,用你自己的开发者身份),可以直接拿去你的后端验签。
右边的「桥调用日志」实时显示页面和宿主之间的每一条消息,CSP 拦截也在这里。

## 6. 真机

1. 「体验者」里加上你自己的手机号(最多 20 人);
2. 用这个手机号登录超级赞用户端;
3. 在「版本」里把开发版「设为体验版」,扫「概览」里的二维码。

安卓调试:用户端「我的 → 设置 → 小程序授权与数据 → 开发者选项」打开「小程序调试」,
电脑 Chrome 打开 `chrome://inspect` 就能看到页面。**不支持直连本机地址**(安卓禁明文 http,
内网 https 证书不被信任)—— 用模拟器 + 快速上传开发版代替。

## 7. 认证

「账号与认证」:个人填姓名 + 身份证号(机器核验,须满 18 岁,真名不公开);企业传营业执照,人工审核。
然后阅读并接受开发者规则。**认证通过、接受规则之后才能提交审核。**

## 8. 提交审核

「展示信息」填好名称、图标、一句话介绍、描述(≥ 10 字)、隐私政策(≥ 20 字)、数据声明,
然后在版本上点「提交审核」,写上给审核员的测试说明。审核按[清单](review.md#审核清单)逐项过,
结论只有通过或驳回(驳回一定带原因代码和说明)。

## 9. 发布

审核通过后点「发布」,用户下次打开就是这个版本;也可以打开「审核通过后自动发布」。
出了问题「回滚到这个版本」一键回到任一发布过的版本。

发布之后,应用出现在公开目录 `/miniapps` 和 App 的下拉抽屉里,直达链接是 `https://chaojizan.cc/m/<AppID>`。
