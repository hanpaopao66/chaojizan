# 超级赞小程序最小模板

三个文件,不需要构建:

- `index.html` —— 同源引 `/_sdk/2/sz-webapp.js`(平台在每个托管 origin 下都放了一份);
- `app.js` —— 展示 open_id、设置主按钮、把 `initData` 交给你的后端验签;
- `superz.json` —— 包清单(`sdk`、`kind`、`orientation`、`background_color`、`spa_fallback`)。

打包上传:

```bash
cd miniapps/_template && zip -r ../hello.zip . -x README.md
```

然后在开发者后台 `/dev/` → 你的应用 → 版本管理 → 上传。完整流程见 `docs/miniapp/quickstart.md`。

本地调试:用任意静态服务器打开 `index.html?sz_mock=1`(SDK 要从 `https://chaojizan.cc/sdk/2/sz-webapp.js` 引,
或者把 `server/static/sdk/2/sz-webapp.js` 复制到本目录)。mock 模式下签名必然无效,你的后端验签会拒绝 —— 这是故意的。
