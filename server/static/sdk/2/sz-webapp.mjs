// src/index.ts
/*!
 * 超级赞小程序 SDK v2 —— window.SuperZ.WebApp(DEV-PROMPTS-39 §5.4、#323)
 *
 * 用法:托管页在 <head> 里同源引一份(每个托管 origin 下都有):
 *
 *   <script src="/_sdk/2/sz-webapp.js"><\/script>
 *   <script>
 *     const app = SuperZ.WebApp
 *     app.ready()
 *     fetch('https://你的后端/login', {method: 'POST', body: app.initData})  // 后端验签
 *   <\/script>
 *
 * 或者把 SDK 打进自己的包:`import { WebApp } from '@superz/miniapp-sdk'`。
 *
 * ## 协议(和宿主两端逐字一致,改一处三处一起改)
 *
 * - 启动参数在 URL 片段里(§5.2):加载时同步读,读完用 history.replaceState 抹掉,
 *   存进 sessionStorage(页面在 WebView 里刷新仍可用;复制地址不会把身份包带出去);
 * - 消息体 {v:2, type, id, method, params, token}:
 *   页面 → 宿主:hello(握手)、call(调用)、notice(CSP 违规等,宿主可以不理)、pong(应答宿主的 ping);
 *   宿主 → 页面:init(带会话令牌与初始状态)、reply、event、ping(网页版确认页面还是这个小程序);
 * - **会话令牌**:宿主每次加载生成、只发给主框架。不带或带错令牌的调用一律被宿主丢弃 ——
 *   原生 JS 通道对页面里所有 frame 都可见,光看主框架 URL 挡不住 iframe 冒充;
 * - 传输:手机端是原生注入的 SuperzBridge 通道(宿主经 window.__szReceive 回话),
 *   web 端是跨域 iframe + postMessage(只认 event.source === window.parent)。
 *
 * 所有方法返回 Promise;同时兼容 Telegram 风格的回调参数。不在宿主里时 inHost=false,调用回 4008。
 * 本地调试加 `?sz_mock=1`:弹窗用浏览器原生、云存储落 localStorage、initData 带 mock=1
 * 且**签名必然无效** —— 开发者后端照常验签就会拒绝,没人能拿 mock 冒充真用户。
 */
var SDK_VERSION = "2.0.0";
var ERRORS = {
  CAPABILITY_NOT_GRANTED: 4001,
  USER_DENIED: 4002,
  NOT_SUPPORTED: 4003,
  INVALID_PARAMS: 4004,
  RATE_LIMITED: 4005,
  QUOTA_EXCEEDED: 4006,
  REV_CONFLICT: 4007,
  NOT_IN_HOST: 4008,
  APP_SUSPENDED: 4009,
  INTERNAL: 5e3,
  NETWORK: 5001
};
var SzError = class extends Error {
  constructor(code, message) {
    super(message);
    this.name = "SzError";
    this.code = code;
  }
};
var BRIDGE_METHODS = [
  "ready",
  "expand",
  "close",
  "setHeaderColor",
  "setBackgroundColor",
  "setClosingConfirmation",
  "mainButton",
  "secondaryButton",
  "backButton",
  "settingsButton",
  "haptic",
  "showPopup",
  "openLink",
  "share",
  "CloudStorage.getItems",
  "CloudStorage.setItem",
  "CloudStorage.removeItems",
  "CloudStorage.getKeys",
  "requestFullscreen",
  "exitFullscreen",
  "lockOrientation",
  "unlockOrientation",
  "requestProfile",
  "legacy.getInitData"
];
var w = typeof window !== "undefined" ? window : {};
var LAUNCH_KEY = "__szLaunch";
var CALL_TIMEOUT = 3e4;
var HELLO_TIMEOUT = 3e3;
function readLaunch() {
  var _a2, _b, _c, _d;
  let out = {};
  const hash = String(((_a2 = w.location) == null ? void 0 : _a2.hash) || "").replace(/^#/, "");
  if (/(^|&)szWebApp(Data|Version)=/.test(hash)) {
    new URLSearchParams(hash).forEach((v, k) => {
      out[k] = v;
    });
    try {
      (_b = w.sessionStorage) == null ? void 0 : _b.setItem(LAUNCH_KEY, JSON.stringify(out));
    } catch (_) {
    }
    try {
      (_c = w.history) == null ? void 0 : _c.replaceState(w.history.state, "", w.location.pathname + w.location.search);
    } catch (_) {
    }
  } else {
    try {
      out = JSON.parse(((_d = w.sessionStorage) == null ? void 0 : _d.getItem(LAUNCH_KEY)) || "{}") || {};
    } catch (_) {
      out = {};
    }
  }
  return out;
}
function parseInitData(raw) {
  const o = {};
  if (!raw) return o;
  new URLSearchParams(raw).forEach((v, k) => {
    o[k] = v;
  });
  if (o.user) {
    try {
      o.user = JSON.parse(o.user);
    } catch (_) {
      delete o.user;
    }
  }
  if (o.auth_date) o.auth_date = Number(o.auth_date);
  return o;
}
function parseJson(s, fallback) {
  try {
    return s ? JSON.parse(s) : fallback;
  } catch (_) {
    return fallback;
  }
}
function versionAtLeast(have, want) {
  const a = String(have).split(".").map(Number);
  const b = String(want).split(".").map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0;
    const y = b[i] || 0;
    if (x !== y) return x > y;
  }
  return true;
}
function brightness(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const lum = (0.299 * (n >> 16) + 0.587 * (n >> 8 & 255) + 0.114 * (n & 255)) / 255;
  return lum < 0.5 ? "dark" : "light";
}
var launch = readLaunch();
var mock = !!w.location && /[?&]sz_mock=1(&|$)/.test(String(w.location.search || ""));
var native = w.SuperzBridge && typeof w.SuperzBridge.postMessage === "function" ? w.SuperzBridge : null;
var parentWin = !native && w.parent && w.parent !== w ? w.parent : null;
var token = "";
var hostOrigin = "*";
var seq = 0;
var initialized = false;
var inHost = !!(native || parentWin);
var pending = {};
var queue = [];
var listeners = {};
function post(msg) {
  if (native) native.postMessage(JSON.stringify(msg));
  else if (parentWin) parentWin.postMessage({ __sz: 2, ...msg }, hostOrigin);
}
function call(method, params = {}, timeout = CALL_TIMEOUT) {
  if (mock) return mockHost(method, params);
  return new Promise((resolve, reject) => {
    if (!inHost) {
      reject(new SzError(ERRORS.NOT_IN_HOST, "不在超级赞里打开,这个功能用不了"));
      return;
    }
    const send = () => {
      const id = ++seq;
      pending[id] = {
        resolve,
        reject,
        timer: setTimeout(() => {
          delete pending[id];
          reject(new SzError(ERRORS.INTERNAL, "宿主没有应答"));
        }, timeout)
      };
      post({ v: 2, type: "call", id, method, params, token });
    };
    if (initialized) send();
    else queue.push({ send, fail: () => reject(new SzError(ERRORS.NOT_IN_HOST, "不在超级赞里打开,这个功能用不了")) });
  });
}
function emit(name, data) {
  for (const fn of (listeners[name] || []).slice()) {
    try {
      fn.call(WebApp, data);
    } catch (e) {
      setTimeout(() => {
        throw e;
      });
    }
  }
}
function receive(msg) {
  var _a2, _b;
  if (!msg || msg.v !== 2) return;
  if (msg.type === "init") {
    if (initialized && msg.token !== token) return;
    token = String(msg.token || "");
    applyInit(msg);
    initialized = true;
    inHost = true;
    queue.splice(0).forEach((q) => q.send());
    return;
  }
  if (msg.type === "reply") {
    const p = pending[msg.id];
    if (!p) return;
    delete pending[msg.id];
    clearTimeout(p.timer);
    if (msg.ok) p.resolve(msg.data);
    else p.reject(new SzError(Number((_a2 = msg.error) == null ? void 0 : _a2.code) || ERRORS.INTERNAL, String(((_b = msg.error) == null ? void 0 : _b.message) || "调用失败")));
    return;
  }
  if (msg.type === "event") applyEvent(String(msg.name), msg.data);
  if (msg.type === "ping") {
    post({ v: 2, type: "pong", nonce: String(msg.nonce || "") });
  }
}
if (native) {
  w.__szReceive = (m) => receive(typeof m === "string" ? parseJson(m, null) : m);
}
if (parentWin && w.addEventListener) {
  w.addEventListener("message", (e) => {
    if (e.source !== parentWin) return;
    const d = e.data;
    if (!d || d.__sz !== 2) return;
    if (d.type === "init" && e.origin && e.origin !== "null") hostOrigin = e.origin;
    receive(d);
  });
}
var state = {
  version: launch.szWebAppVersion || "2.0",
  platform: launch.szWebAppPlatform || (native ? "unknown" : "web"),
  themeParams: parseJson(launch.szWebAppThemeParams, {}),
  colorScheme: "light",
  viewportHeight: w.innerHeight || 0,
  viewportStableHeight: w.innerHeight || 0,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  isExpanded: false,
  isFullscreen: false,
  isActive: true,
  isClosingConfirmationEnabled: false,
  headerColor: "",
  backgroundColor: "",
  capabilities: [],
  initData: launch.szWebAppData || ""
};
state.colorScheme = brightness(state.themeParams.bg_color) || "light";
function cssVars() {
  var _a2;
  const root = (_a2 = w.document) == null ? void 0 : _a2.documentElement;
  if (!(root == null ? void 0 : root.style)) return;
  const set = (k, v) => root.style.setProperty(k, v);
  for (const [k, v] of Object.entries(state.themeParams)) {
    if (typeof v === "string") set(`--sz-theme-${k.replace(/_/g, "-")}`, v);
  }
  set("--sz-viewport-height", `${state.viewportHeight}px`);
  set("--sz-viewport-stable-height", `${state.viewportStableHeight}px`);
  for (const side of ["top", "bottom", "left", "right"]) {
    set(`--sz-safe-area-inset-${side}`, `${state.safeAreaInset[side] || 0}px`);
    set(`--sz-content-safe-area-inset-${side}`, `${state.contentSafeAreaInset[side] || 0}px`);
  }
  root.style.colorScheme = state.colorScheme;
}
function applyInit(m) {
  if (m.version) state.version = String(m.version);
  if (m.platform) state.platform = m.platform;
  if (m.themeParams) state.themeParams = m.themeParams;
  state.colorScheme = m.colorScheme || brightness(state.themeParams.bg_color) || "light";
  if (m.viewport) {
    state.viewportHeight = Number(m.viewport.height) || state.viewportHeight;
    state.viewportStableHeight = Number(m.viewport.stableHeight) || state.viewportHeight;
    state.isExpanded = !!m.viewport.isExpanded;
  }
  if (m.safeArea) state.safeAreaInset = m.safeArea;
  if (m.contentSafeArea) state.contentSafeAreaInset = m.contentSafeArea;
  if (Array.isArray(m.capabilities)) state.capabilities = m.capabilities;
  state.isFullscreen = !!m.isFullscreen;
  cssVars();
}
function applyEvent(name, d) {
  var _a2, _b;
  switch (name) {
    case "themeChanged":
      state.themeParams = (d == null ? void 0 : d.themeParams) || state.themeParams;
      state.colorScheme = (d == null ? void 0 : d.colorScheme) || brightness(state.themeParams.bg_color) || state.colorScheme;
      cssVars();
      break;
    case "viewportChanged":
      state.viewportHeight = Number(d == null ? void 0 : d.height) || state.viewportHeight;
      if (d == null ? void 0 : d.isStateStable) state.viewportStableHeight = state.viewportHeight;
      state.isExpanded = !!(d == null ? void 0 : d.isExpanded);
      cssVars();
      break;
    case "safeAreaChanged":
      state.safeAreaInset = d || state.safeAreaInset;
      cssVars();
      break;
    case "contentSafeAreaChanged":
      state.contentSafeAreaInset = d || state.contentSafeAreaInset;
      cssVars();
      break;
    case "fullscreenChanged":
      state.isFullscreen = !!(d == null ? void 0 : d.isFullscreen);
      break;
    case "activated":
    case "deactivated":
      state.isActive = name === "activated";
      break;
    case "mainButtonClicked":
      MainButton._fire();
      break;
    case "secondaryButtonClicked":
      SecondaryButton._fire();
      break;
    case "backButtonClicked":
      BackButton._fire();
      break;
    case "settingsButtonClicked":
      SettingsButton._fire();
      break;
    case "clearLocalData":
      try {
        (_a2 = w.localStorage) == null ? void 0 : _a2.clear();
        (_b = w.sessionStorage) == null ? void 0 : _b.clear();
      } catch (_) {
      }
      break;
  }
  emit(name, d);
}
var BottomButton = class {
  constructor(method, text) {
    this.method = method;
    this.color = "";
    this.textColor = "";
    this.isVisible = false;
    this.isActive = true;
    this.isProgressVisible = false;
    this.position = "left";
    this.handlers = [];
    this.scheduled = false;
    this.text = text;
  }
  /** @internal */
  _fire() {
    if (!this.isActive || this.isProgressVisible) return;
    for (const fn of this.handlers.slice()) fn();
  }
  _sync() {
    if (!this.scheduled) {
      this.scheduled = true;
      Promise.resolve().then(() => {
        this.scheduled = false;
        call(this.method, {
          text: this.text,
          color: this.color,
          text_color: this.textColor,
          is_visible: this.isVisible,
          is_active: this.isActive,
          is_progress_visible: this.isProgressVisible,
          position: this.position
        }).catch(() => void 0);
      });
    }
    return this;
  }
  setText(text) {
    this.text = String(text).slice(0, 64);
    return this._sync();
  }
  show() {
    this.isVisible = true;
    return this._sync();
  }
  hide() {
    this.isVisible = false;
    return this._sync();
  }
  enable() {
    this.isActive = true;
    return this._sync();
  }
  disable() {
    this.isActive = false;
    return this._sync();
  }
  showProgress(_leaveActive) {
    this.isProgressVisible = true;
    return this._sync();
  }
  hideProgress() {
    this.isProgressVisible = false;
    return this._sync();
  }
  setParams(p) {
    if (p.text !== void 0) this.text = String(p.text).slice(0, 64);
    if (p.color !== void 0) this.color = p.color;
    if (p.text_color !== void 0) this.textColor = p.text_color;
    if (p.is_visible !== void 0) this.isVisible = !!p.is_visible;
    if (p.is_active !== void 0) this.isActive = !!p.is_active;
    if (p.is_progress_visible !== void 0) this.isProgressVisible = !!p.is_progress_visible;
    if (p.position !== void 0) this.position = p.position;
    return this._sync();
  }
  onClick(fn) {
    this.handlers.push(fn);
    return this;
  }
  offClick(fn) {
    this.handlers = this.handlers.filter((h) => h !== fn);
    return this;
  }
};
var HeaderButton = class {
  constructor(method) {
    this.method = method;
    this.isVisible = false;
    this.handlers = [];
  }
  /** @internal */
  _fire() {
    for (const fn of this.handlers.slice()) fn();
  }
  show() {
    this.isVisible = true;
    call(this.method, { is_visible: true }).catch(() => void 0);
    return this;
  }
  hide() {
    this.isVisible = false;
    call(this.method, { is_visible: false }).catch(() => void 0);
    return this;
  }
  onClick(fn) {
    this.handlers.push(fn);
    return this;
  }
  offClick(fn) {
    this.handlers = this.handlers.filter((h) => h !== fn);
    return this;
  }
};
var MainButton = new BottomButton("mainButton", "继续");
var SecondaryButton = new BottomButton("secondaryButton", "取消");
var BackButton = new HeaderButton("backButton");
var SettingsButton = new HeaderButton("settingsButton");
function withCb(p, cb, errFirst = false) {
  if (typeof cb === "function") {
    p.then((v) => errFirst ? cb(null, v) : cb(v), (e) => errFirst ? cb(e) : void 0);
  }
  return p;
}
var CloudStorage = {
  /** 写一个键。带 ifRev 时版本不符回 4007(REV_CONFLICT);ifRev=0 表示「必须还不存在」 */
  setItem(key, value, opts, cb) {
    if (typeof opts === "function") {
      cb = opts;
      opts = void 0;
    }
    const ifRev = opts == null ? void 0 : opts.ifRev;
    return withCb(call(
      "CloudStorage.setItem",
      ifRev === void 0 ? { key, value } : { key, value, if_rev: ifRev }
    ), cb, true);
  },
  getItem(key, cb) {
    return withCb(CloudStorage.getItemsWithRev([key]).then((r) => {
      var _a2, _b;
      return (_b = (_a2 = r[key]) == null ? void 0 : _a2.value) != null ? _b : null;
    }), cb, true);
  },
  getItems(keys, cb) {
    return withCb(CloudStorage.getItemsWithRev(keys).then((r) => {
      var _a2, _b;
      const o = {};
      for (const k of keys) o[k] = (_b = (_a2 = r[k]) == null ? void 0 : _a2.value) != null ? _b : null;
      return o;
    }), cb, true);
  },
  /** 带版本号读(做 ifRev 并发控制时用)。一次最多 100 个键 */
  getItemsWithRev(keys) {
    return call("CloudStorage.getItems", { keys }).then((r) => r.items || {});
  },
  removeItem(key, cb) {
    return withCb(CloudStorage.removeItems([key]), cb, true);
  },
  removeItems(keys, cb) {
    return withCb(call("CloudStorage.removeItems", { keys }).then(() => true), cb, true);
  },
  /** 列键。prefix 可选;超过 limit 时用返回的 next_cursor 翻页 */
  getKeys(opts, cb) {
    if (typeof opts === "function") {
      cb = opts;
      opts = void 0;
    }
    const o = opts || {};
    return withCb(CloudStorage.getKeysPage(o).then(async (page) => {
      let keys = page.keys;
      let next = page.next_cursor;
      while (next && !o.limit) {
        const more = await CloudStorage.getKeysPage({ ...o, cursor: next });
        keys = keys.concat(more.keys);
        next = more.next_cursor;
      }
      return keys;
    }), cb, true);
  },
  getKeysPage(o = {}) {
    return call("CloudStorage.getKeys", { prefix: o.prefix || "", cursor: o.cursor || "", limit: o.limit || 500 });
  }
};
var HapticFeedback = {
  impactOccurred(style = "light") {
    call("haptic", { type: "impact", style }).catch(() => void 0);
    return HapticFeedback;
  },
  notificationOccurred(type = "success") {
    call("haptic", { type: "notification", style: type }).catch(() => void 0);
    return HapticFeedback;
  },
  selectionChanged() {
    call("haptic", { type: "selection" }).catch(() => void 0);
    return HapticFeedback;
  }
};
function showPopup(params, cb) {
  const buttons = params.buttons && params.buttons.length ? params.buttons : [{ type: "close" }];
  if (!params.message || buttons.length > 3) {
    return Promise.reject(new SzError(ERRORS.INVALID_PARAMS, "message 必填,按钮最多 3 个"));
  }
  const p = call("showPopup", { ...params, buttons }).then((r) => r && r.button_id != null ? String(r.button_id) : null);
  p.then((id) => emit("popupClosed", { button_id: id }), () => void 0);
  return withCb(p, cb);
}
var WebApp = {
  get version() {
    return state.version;
  },
  sdkVersion: SDK_VERSION,
  get platform() {
    return state.platform;
  },
  get colorScheme() {
    return state.colorScheme;
  },
  get themeParams() {
    return state.themeParams;
  },
  /** 原样交给你的后端验签。**不要**在前端信任它的内容 —— 用 initDataUnsafe 只做展示 */
  get initData() {
    return state.initData;
  },
  get initDataUnsafe() {
    return parseInitData(state.initData);
  },
  get inHost() {
    return mock || inHost;
  },
  get isMock() {
    return mock;
  },
  get isExpanded() {
    return state.isExpanded;
  },
  get isFullscreen() {
    return state.isFullscreen;
  },
  get isActive() {
    return state.isActive;
  },
  get viewportHeight() {
    return state.viewportHeight;
  },
  get viewportStableHeight() {
    return state.viewportStableHeight;
  },
  get safeAreaInset() {
    return state.safeAreaInset;
  },
  get contentSafeAreaInset() {
    return state.contentSafeAreaInset;
  },
  get isClosingConfirmationEnabled() {
    return state.isClosingConfirmationEnabled;
  },
  get headerColor() {
    return state.headerColor;
  },
  get backgroundColor() {
    return state.backgroundColor;
  },
  /** 宿主给这个应用开了哪些能力(basic 之外的要在开发者后台申请) */
  get capabilities() {
    return state.capabilities.slice();
  },
  startParam() {
    return launch.szWebAppStartParam || parseInitData(state.initData).start_param || "";
  },
  isVersionAtLeast(v) {
    return versionAtLeast(state.version, v);
  },
  ready() {
    return call("ready").then(() => void 0);
  },
  expand() {
    return call("expand").then(() => void 0);
  },
  close() {
    return call("close").then(() => void 0);
  },
  setHeaderColor(color) {
    state.headerColor = color;
    return call("setHeaderColor", { color }).then(() => void 0);
  },
  setBackgroundColor(color) {
    state.backgroundColor = color;
    return call("setBackgroundColor", { color }).then(() => void 0);
  },
  enableClosingConfirmation() {
    state.isClosingConfirmationEnabled = true;
    return call("setClosingConfirmation", { enabled: true }).then(() => void 0);
  },
  disableClosingConfirmation() {
    state.isClosingConfirmationEnabled = false;
    return call("setClosingConfirmation", { enabled: false }).then(() => void 0);
  },
  onEvent(name, fn) {
    (listeners[name] = listeners[name] || []).push(fn);
  },
  offEvent(name, fn) {
    listeners[name] = (listeners[name] || []).filter((h) => h !== fn);
  },
  showPopup,
  showAlert(message, cb) {
    return withCb(showPopup({ message, buttons: [{ type: "close" }] }).then(() => void 0), cb);
  },
  showConfirm(message, cb) {
    return withCb(showPopup({ message, buttons: [{ id: "ok", type: "ok" }, { type: "cancel" }] }).then((id) => id === "ok"), cb);
  },
  /** 在系统浏览器打开(宿主先弹「即将离开超级赞」) */
  openLink(url) {
    if (!/^https?:\/\//i.test(url)) return Promise.reject(new SzError(ERRORS.INVALID_PARAMS, "只能打开 http(s) 链接"));
    return call("openLink", { url }).then(() => void 0);
  },
  /** 系统分享面板。url 可省(默认分享这个小程序的直达链接) */
  share(p) {
    return call("share", p).then((r) => !!(r == null ? void 0 : r.shared));
  },
  requestFullscreen() {
    return call("requestFullscreen").then(() => void 0);
  },
  exitFullscreen() {
    return call("exitFullscreen").then(() => void 0);
  },
  lockOrientation() {
    return call("lockOrientation").then(() => void 0);
  },
  unlockOrientation() {
    return call("unlockOrientation").then(() => void 0);
  },
  /**
   * 请求昵称和头像(要申请 profile 能力;首次宿主会弹确认,用户可在设置里撤回)。
   * 同意后当场拿到一份**新签发的** initData —— 把它交给你的后端验签,页面自己报的昵称不可信。
   */
  requestProfile(cb) {
    return withCb(call("requestProfile").then((r) => {
      state.initData = r.init_data;
      return { initData: r.init_data, user: parseInitData(r.init_data).user };
    }), cb, true);
  },
  MainButton,
  SecondaryButton,
  BackButton,
  SettingsButton,
  HapticFeedback,
  CloudStorage,
  ERRORS,
  SzError
};
function mockHost(method, p) {
  var _a2, _b, _c, _d;
  const ls = w.localStorage;
  const K = (k) => `sz_mock_kv:${k}`;
  const read = (k) => parseJson((ls == null ? void 0 : ls.getItem(K(k))) || "", null);
  switch (method) {
    case "showPopup": {
      const btns = p.buttons || [];
      const ok = btns.find((b) => b.type !== "cancel" && b.type !== "close");
      if (btns.length === 1) {
        (_a2 = w.alert) == null ? void 0 : _a2.call(w, p.message);
        return Promise.resolve({ button_id: (_b = btns[0].id) != null ? _b : null });
      }
      const yes = w.confirm ? w.confirm(p.message) : true;
      return Promise.resolve({ button_id: yes ? (_c = ok == null ? void 0 : ok.id) != null ? _c : null : null });
    }
    case "openLink":
      (_d = w.open) == null ? void 0 : _d.call(w, p.url, "_blank", "noopener");
      return Promise.resolve(true);
    case "share":
      console.info("[sz_mock] share", p);
      return Promise.resolve({ shared: true });
    case "CloudStorage.getItems": {
      const items = {};
      for (const k of p.keys || []) items[k] = read(k);
      return Promise.resolve({ items });
    }
    case "CloudStorage.setItem": {
      if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(p.key || "")) return Promise.reject(new SzError(4004, "键格式不对"));
      const cur = read(p.key);
      if (p.if_rev !== void 0 && (cur ? cur.rev : 0) !== p.if_rev) {
        return Promise.reject(new SzError(4007, "版本号不符"));
      }
      const rev = (cur ? cur.rev : 0) + 1;
      ls == null ? void 0 : ls.setItem(K(p.key), JSON.stringify({ value: String(p.value), rev }));
      return Promise.resolve({ key: p.key, rev });
    }
    case "CloudStorage.removeItems":
      for (const k of p.keys || []) ls == null ? void 0 : ls.removeItem(K(k));
      return Promise.resolve({ removed: (p.keys || []).length });
    case "CloudStorage.getKeys": {
      const keys = [];
      for (let i = 0; i < ((ls == null ? void 0 : ls.length) || 0); i++) {
        const k = ls.key(i);
        if (k && k.startsWith("sz_mock_kv:")) {
          const key = k.slice("sz_mock_kv:".length);
          if (!p.prefix || key.startsWith(p.prefix)) keys.push(key);
        }
      }
      return Promise.resolve({ keys: keys.sort(), next_cursor: null });
    }
    case "requestProfile":
      return Promise.resolve({ init_data: mockInitData({ nickname: "调试用户" }) });
    default:
      console.info("[sz_mock]", method, p);
      return Promise.resolve(true);
  }
}
function mockInitData(extra = {}) {
  const user = JSON.stringify({ language_code: "zh-CN", open_id: "o_mockmockmockmockmockmockmo", ...extra });
  return new URLSearchParams({
    app_id: "szmock",
    auth_date: String(Math.floor(Date.now() / 1e3)),
    launch_id: "mock",
    mock: "1",
    sig_kid: "mock",
    user,
    hash: "0".repeat(64),
    signature: "mock"
  }).toString();
}
if (mock && !state.initData) {
  state.initData = mockInitData();
  state.platform = "web";
}
if (!mock && inHost) {
  const hello = () => post({ v: 2, type: "hello", sdk: SDK_VERSION });
  hello();
  if (parentWin) {
    setTimeout(() => {
      if (!initialized) {
        inHost = false;
        queue.splice(0).forEach((q) => q.fail());
      }
    }, HELLO_TIMEOUT);
  }
}
var _a;
if ((_a = w.document) == null ? void 0 : _a.addEventListener) {
  w.document.addEventListener("securitypolicyviolation", (e) => {
    post({
      v: 2,
      type: "notice",
      name: "csp",
      token,
      data: {
        directive: e.effectiveDirective || e.violatedDirective,
        blocked: String(e.blockedURI || "").replace(/^(\w+:\/\/[^/?#]+).*$/, "$1")
      }
    });
  });
}
cssVars();
w.SuperZ = w.SuperZ || {};
w.SuperZ.WebApp = WebApp;
if (!w.superz) {
  w.superz = {
    version: 1,
    get inHost() {
      return WebApp.inHost;
    },
    ready: () => WebApp.ready(),
    close: () => WebApp.close(),
    expand: () => WebApp.expand(),
    themeParams: () => Promise.resolve({ brightness: state.colorScheme, ...state.themeParams }),
    getInitData: () => call("legacy.getInitData")
  };
}
var src_default = WebApp;
export {
  BRIDGE_METHODS,
  ERRORS,
  SDK_VERSION,
  SzError,
  WebApp,
  src_default as default
};
