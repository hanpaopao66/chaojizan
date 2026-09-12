// 最小模板:不需要任何构建步骤,改完直接打 zip 上传。
// 完整的 API 见开发者文档「SDK 参考」;验签见「服务端」那一页。
(function () {
  var app = window.SuperZ.WebApp
  var $ = function (id) { return document.getElementById(id) }

  // ① initDataUnsafe 只用来展示。**身份以你后端验签的结果为准**
  var user = app.initDataUnsafe.user || {}
  $('open-id').textContent = user.open_id || '(不在宿主里)'
  $('platform').textContent = app.platform + (app.initDataUnsafe.env === 'sim' ? '(模拟器)' : '')
  $('version').textContent = app.version + ' · SDK ' + app.sdkVersion
  if (user.nickname) $('who').textContent = user.nickname

  // ② 主按钮是宿主原生画的:页面只管文字和点了之后做什么
  app.MainButton.setText('把 initData 交给我的后端验签').show().onClick(function () {
    app.MainButton.showProgress()
    // 换成你自己的后端地址,并在开发者后台「服务器域名」里声明它(否则 CSP 会拦下)
    fetch('https://api.example.com/superz/login', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: app.initData,
    }).then(function (r) { return r.json() })
      .then(function (d) { $('verify').textContent = d.ok ? '验签通过:' + d.open_id : '验签失败' })
      .catch(function () { $('verify').textContent = '请求失败(后端地址是示例,换成你自己的)' })
      .then(function () { app.MainButton.hideProgress() })
  })

  // ③ 告诉宿主页面画好了:宿主撤掉启动页
  app.ready()
})()
