/*!
 * 超级赞小程序桥(#279 / #292)。页面在 <head> 里引这一个文件就够:
 *
 *   <script src="https://<域名>/mini-app-bridge.js"></script>
 *
 * 引完之后 window.superz 就有了,用法和之前一样:
 *
 *   await superz.ready();
 *   const theme = await superz.themeParams();
 *   const pack  = await superz.getInitData();   // 需要申请 initData 权限
 *
 * ## 为什么要有这个文件(以前是宿主注入的)
 *
 * 手机端小程序跑在原生 WebView 里,宿主可以往页面里注入 JS,
 * 所以页面什么都不用引。**但 web 端不行** —— 那里小程序跑在跨域 iframe 里,
 * 而浏览器的同源策略明确禁止父页面往跨域 iframe 注入脚本。
 * 这不是权限没开,是安全模型本身。
 *
 * Telegram 也是这么解决的:它要求页面引 telegram-web-app.js,
 * 那个脚本用 postMessage 和宿主通信。我们照搬。
 *
 * ## 一份脚本两种通道
 *
 * - 有 window.SuperzBridge(原生 WebView 注入的通道)→ 走它;
 * - 否则(iframe / 普通浏览器)→ 走 window.parent.postMessage。
 *
 * 所以老小程序不用改也能继续在手机上跑(宿主仍然会注入),
 * 引了这个脚本之后手机和 web 两边都能跑。
 *
 * ## 安全边界
 *
 * - **token 永远不会进到页面里。** 身份只有 getInitData() 一条路,
 *   拿到的是服务端签的 HMAC 身份包,分钟级时效;
 * - postMessage 回来的消息**必须验 event.source**:只认宿主那一帧,
 *   别的 iframe 或者同页面里的第三方脚本伪造的一概丢掉;
 * - 桥没有任何收集卡号/密码的能力。支付不进小程序。
 */
(function () {
  'use strict';
  if (window.superz) return;

  var cbs = {};
  var seq = 0;

  // 原生 WebView 注入的通道。iframe 里没有,那时候走 postMessage
  var native = window.SuperzBridge &&
      typeof window.SuperzBridge.postMessage === 'function'
      ? window.SuperzBridge : null;

  // ⚠️ 只认真正的宿主。iframe 里 parent 就是宿主页;
  // 顶层打开(有人直接访问小程序地址)时 parent === window,那时候没有宿主
  var host = (!native && window.parent !== window) ? window.parent : null;

  function send(payload) {
    if (native) {
      native.postMessage(JSON.stringify(payload));
      return true;
    }
    if (host) {
      // targetOrigin 用 '*':宿主的 origin 页面事先并不知道,
      // 而 payload 里**不含任何机密**(只有方法名和参数)。
      // 真正要防的是反方向 —— 宿主发回来的东西,那一侧在下面验了 source
      host.postMessage({ __superz: 1, payload: payload }, '*');
      return true;
    }
    return false;
  }

  function call(method, params) {
    return new Promise(function (resolve, reject) {
      var id = ++seq;
      cbs[id] = [resolve, reject];
      if (!send({ id: id, method: method, params: params || {} })) {
        delete cbs[id];
        reject(new Error(
            '不在超级赞里打开,这个功能用不了。请回 App 或小程序面板里进入'));
      }
    });
  }

  function resolve(id, ok, data) {
    var c = cbs[id];
    if (!c) return;
    delete cbs[id];
    (ok ? c[0] : c[1])(ok ? data : new Error(String(data)));
  }

  window.superz = {
    version: 1,
    /** 宿主在不在。页面可以据此隐藏"只有在超级赞里才有意义"的入口 */
    inHost: !!(native || host),
    _resolve: resolve,   // 原生注入的宿主直接调这个
    _call: call,
    ready: function () { return call('ready'); },
    close: function () { return call('close'); },
    expand: function () { return call('expand'); },
    themeParams: function () { return call('themeParams'); },
    getInitData: function () { return call('getInitData'); }
  };

  // iframe 通道:收宿主的应答。
  //
  // **验 event.source 而不是 event.origin** —— 宿主页的 origin 页面不知道
  // (App 的 web 版可能部署在任何域名下),但"消息是不是从我的父窗口来的"
  // 是确定的。别的 iframe、同页面里的第三方脚本都伪造不了 source。
  if (host) {
    window.addEventListener('message', function (e) {
      if (e.source !== host) return;
      var d = e.data;
      if (!d || d.__superz !== 1 || !d.reply) return;
      resolve(d.reply.id, !!d.reply.ok, d.reply.data);
    });
  }

  document.dispatchEvent(new Event('superzready'));
})();
