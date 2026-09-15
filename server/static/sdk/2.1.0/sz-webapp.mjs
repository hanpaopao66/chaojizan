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
 *
 * 同时挂 window.Telegram.WebApp:Telegram Mini App 的前端把 telegram-web-app.js 换成这个地址就能跑(2.1.0 起)。
 */
var SDK_VERSION = "2.1.0";
var PROTOCOL_VERSION = "2.1";
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
  "setBottomBarColor",
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
function toHex(color) {
  const s = String(color != null ? color : "").trim();
  let m = /^#([0-9a-f]{6})$/i.exec(s);
  if (m) return "#" + m[1].toUpperCase();
  m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s);
  if (m) return ("#" + m[1] + m[1] + m[2] + m[2] + m[3] + m[3]).toUpperCase();
  m = /^rgba?\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})(?:,\s*[\d.]+)?\)$/i.exec(s);
  if (m && [m[1], m[2], m[3]].every((x) => Number(x) <= 255)) {
    return "#" + [m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, "0")).join("").toUpperCase();
  }
  return null;
}
var DERIVED_THEME = [
  ["header_bg_color", "bg_color"],
  ["bottom_bar_bg_color", "secondary_bg_color"],
  ["section_bg_color", "secondary_bg_color"],
  ["section_header_text_color", "hint_color"],
  ["section_separator_color", "line_color"],
  ["subtitle_text_color", "hint_color"]
];
function withDerived(t) {
  const out = { ...t || {} };
  for (const [key, from] of DERIVED_THEME) {
    if (!out[key] && out[from]) out[key] = out[from];
  }
  return out;
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
var SIDES = ["top", "bottom", "left", "right"];
var state = {
  version: launch.szWebAppVersion || "2.0",
  platform: launch.szWebAppPlatform || (native ? "unknown" : "web"),
  themeParams: withDerived(parseJson(launch.szWebAppThemeParams, {})),
  colorScheme: "light",
  viewportHeight: w.innerHeight || 0,
  viewportStableHeight: w.innerHeight || 0,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  isExpanded: false,
  isFullscreen: false,
  isOrientationLocked: false,
  isActive: true,
  isClosingConfirmationEnabled: false,
  capabilities: [],
  initData: launch.szWebAppData || ""
};
state.colorScheme = brightness(state.themeParams.bg_color) || "light";
var colorSpec = { header: "", background: "", bottomBar: "" };
var COLOR_KEYS = {
  header: ["bg_color", "secondary_bg_color", "header_bg_color"],
  background: ["bg_color", "secondary_bg_color"],
  bottomBar: ["bg_color", "secondary_bg_color", "bottom_bar_bg_color"]
};
var COLOR_METHOD = {
  header: "setHeaderColor",
  background: "setBackgroundColor",
  bottomBar: "setBottomBarColor"
};
var COLOR_DEFAULT = {
  header: ["header_bg_color", "bg_color"],
  background: ["bg_color"],
  bottomBar: ["bottom_bar_bg_color", "secondary_bg_color"]
};
function resolveColor(spec) {
  return spec.charAt(0) === "#" ? spec : String(state.themeParams[spec] || "");
}
function effectiveColor(which) {
  const own = colorSpec[which] && resolveColor(colorSpec[which]);
  if (own) return own;
  for (const k of COLOR_DEFAULT[which]) if (state.themeParams[k]) return state.themeParams[k];
  return "";
}
function setColor(which, color) {
  const key = COLOR_KEYS[which].indexOf(String(color)) >= 0 ? String(color) : "";
  const spec = key || toHex(color);
  const hex = spec ? resolveColor(spec) : "";
  if (!spec || !hex) {
    return Promise.reject(new SzError(
      ERRORS.INVALID_PARAMS,
      `颜色要写 #RRGGBB,或者主题色的键:${COLOR_KEYS[which].join(" / ")}`
    ));
  }
  colorSpec[which] = spec;
  return call(COLOR_METHOD[which], { color: hex }).then(() => void 0);
}
function tgContentInset() {
  const out = { top: 0, bottom: 0, left: 0, right: 0 };
  for (const side of SIDES) {
    out[side] = Math.max(0, (Number(state.contentSafeAreaInset[side]) || 0) - (Number(state.safeAreaInset[side]) || 0));
  }
  return out;
}
function cssVars() {
  var _a2;
  const root = (_a2 = w.document) == null ? void 0 : _a2.documentElement;
  if (!(root == null ? void 0 : root.style)) return;
  const set = (k, v) => root.style.setProperty(k, v);
  for (const [k, v] of Object.entries(state.themeParams)) {
    if (typeof v !== "string") continue;
    const name = k.replace(/_/g, "-");
    set(`--sz-theme-${name}`, v);
    set(`--tg-theme-${name}`, v);
  }
  set("--tg-color-scheme", state.colorScheme);
  for (const p of ["sz", "tg"]) {
    set(`--${p}-viewport-height`, `${state.viewportHeight}px`);
    set(`--${p}-viewport-stable-height`, `${state.viewportStableHeight}px`);
  }
  const tg = tgContentInset();
  for (const side of SIDES) {
    const safe = `${Number(state.safeAreaInset[side]) || 0}px`;
    set(`--sz-safe-area-inset-${side}`, safe);
    set(`--tg-safe-area-inset-${side}`, safe);
    set(`--sz-content-safe-area-inset-${side}`, `${Number(state.contentSafeAreaInset[side]) || 0}px`);
    set(`--tg-content-safe-area-inset-${side}`, `${tg[side]}px`);
  }
  root.style.colorScheme = state.colorScheme;
}
function resyncKeyedColors(before) {
  for (const which of Object.keys(colorSpec)) {
    const spec = colorSpec[which];
    if (!spec || spec.charAt(0) === "#") continue;
    const hex = resolveColor(spec);
    if (hex && hex !== before[spec]) call(COLOR_METHOD[which], { color: hex }).catch(() => void 0);
  }
}
function applyInit(m) {
  if (m.version) state.version = String(m.version);
  if (m.platform) state.platform = m.platform;
  if (m.themeParams) state.themeParams = withDerived(m.themeParams);
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
    case "themeChanged": {
      const before = state.themeParams;
      state.themeParams = withDerived((d == null ? void 0 : d.themeParams) || state.themeParams);
      state.colorScheme = (d == null ? void 0 : d.colorScheme) || brightness(state.themeParams.bg_color) || state.colorScheme;
      cssVars();
      resyncKeyedColors(before);
      break;
    }
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
    case "fullscreenFailed":
      d = { ...d || {}, error: (d == null ? void 0 : d.error) || "UNSUPPORTED" };
      if (d.error === "ALREADY_FULLSCREEN") state.isFullscreen = true;
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
    this._color = "";
    this._textColor = "";
    this._visible = false;
    this._active = true;
    this._progress = false;
    this._shine = false;
    this._position = "left";
    this.handlers = [];
    this.scheduled = false;
    this._text = text;
  }
  /** 'main' / 'secondary'(Telegram 的 BottomButton.type) */
  get type() {
    return this.method === "mainButton" ? "main" : "secondary";
  }
  get text() {
    return this._text;
  }
  set text(v) {
    this.setParams({ text: v });
  }
  get color() {
    if (this._color) return this._color;
    return (this.method === "mainButton" ? state.themeParams.button_color : effectiveColor("bottomBar")) || "";
  }
  set color(v) {
    this.setParams({ color: v });
  }
  get textColor() {
    if (this._textColor) return this._textColor;
    return (this.method === "mainButton" ? state.themeParams.button_text_color : state.themeParams.button_color) || "";
  }
  set textColor(v) {
    this.setParams({ text_color: v });
  }
  get isVisible() {
    return this._visible;
  }
  set isVisible(v) {
    this.setParams({ is_visible: v });
  }
  get isActive() {
    return this._active;
  }
  set isActive(v) {
    this.setParams({ is_active: v });
  }
  get isProgressVisible() {
    return this._progress;
  }
  get hasShineEffect() {
    return this._shine;
  }
  set hasShineEffect(v) {
    this.setParams({ has_shine_effect: v });
  }
  get position() {
    return this._position;
  }
  set position(v) {
    this.setParams({ position: v });
  }
  /** @internal */
  _fire() {
    if (!this._active) return;
    for (const fn of this.handlers.slice()) fn();
  }
  _sync() {
    if (!this.scheduled) {
      this.scheduled = true;
      Promise.resolve().then(() => {
        this.scheduled = false;
        call(this.method, {
          text: this._text,
          color: this._color,
          text_color: this._textColor,
          is_visible: this._visible,
          is_active: this._active,
          is_progress_visible: this._progress,
          has_shine_effect: this._shine,
          position: this._position
        }).catch(() => void 0);
      });
    }
    return this;
  }
  setText(text) {
    return this.setParams({ text });
  }
  show() {
    return this.setParams({ is_visible: true });
  }
  hide() {
    return this.setParams({ is_visible: false });
  }
  enable() {
    return this.setParams({ is_active: true });
  }
  disable() {
    return this.setParams({ is_active: false });
  }
  /** 显示加载中。和 Telegram 一样:不传 leaveActive 时按钮在加载中不可点 */
  showProgress(leaveActive) {
    this._active = !!leaveActive;
    this._progress = true;
    return this._sync();
  }
  /** 取消加载中,按钮回到可点(Telegram 同样如此) */
  hideProgress() {
    this._active = true;
    this._progress = false;
    return this._sync();
  }
  setParams(p) {
    if (p.text !== void 0) this._text = String(p.text).trim().slice(0, 64);
    if (p.color !== void 0) this._color = p.color === null || p.color === false ? "" : toHex(p.color) || this._color;
    if (p.text_color !== void 0) {
      this._textColor = p.text_color === null || p.text_color === false ? "" : toHex(p.text_color) || this._textColor;
    }
    if (p.is_visible !== void 0) this._visible = !!p.is_visible;
    if (p.is_active !== void 0) this._active = !!p.is_active;
    if (p.is_progress_visible !== void 0) this._progress = !!p.is_progress_visible;
    if (p.has_shine_effect !== void 0) this._shine = !!p.has_shine_effect;
    if (p.position && ["left", "right", "top", "bottom"].indexOf(p.position) >= 0) this._position = p.position;
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
    this._visible = false;
    this.handlers = [];
  }
  get isVisible() {
    return this._visible;
  }
  set isVisible(v) {
    if (v) this.show();
    else this.hide();
  }
  /** @internal */
  _fire() {
    for (const fn of this.handlers.slice()) fn();
  }
  show() {
    this._visible = true;
    call(this.method, { is_visible: true }).catch(() => void 0);
    return this;
  }
  hide() {
    this._visible = false;
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
var unsafeOf = "";
var unsafeCache = {};
function unsafeData() {
  if (unsafeOf !== state.initData || !unsafeCache) {
    unsafeOf = state.initData;
    unsafeCache = parseInitData(state.initData);
  }
  return unsafeCache;
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
    return unsafeData();
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
  get isOrientationLocked() {
    return state.isOrientationLocked;
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
  /** 顶栏现在的颜色(页面设过的,否则主题的 header_bg_color) */
  get headerColor() {
    return effectiveColor("header");
  },
  get backgroundColor() {
    return effectiveColor("background");
  },
  /** 底栏(主按钮 / 次按钮那一条)现在的颜色 */
  get bottomBarColor() {
    return effectiveColor("bottomBar");
  },
  /** 宿主给这个应用开了哪些能力(basic 之外的要在开发者后台申请) */
  get capabilities() {
    return state.capabilities.slice();
  },
  startParam() {
    return launch.szWebAppStartParam || unsafeData().start_param || "";
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
  /** #RRGGBB(也收 #RGB、rgb()),或者主题色的键 'bg_color' / 'secondary_bg_color' / 'header_bg_color' —— 写键的跟着亮暗走 */
  setHeaderColor(color) {
    return setColor("header", color);
  },
  /** 同 setHeaderColor;键可以是 'bg_color' / 'secondary_bg_color' */
  setBackgroundColor(color) {
    return setColor("background", color);
  },
  /** 底栏的底色;键可以是 'bg_color' / 'secondary_bg_color' / 'bottom_bar_bg_color'。宿主 2.1 起 */
  setBottomBarColor(color) {
    return setColor("bottomBar", color);
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
  /** 沉浸式全屏(宿主 2.1 起所有应用都能用)。结果看 fullscreenChanged / fullscreenFailed 事件 */
  requestFullscreen() {
    return call("requestFullscreen").then(() => void 0);
  },
  exitFullscreen() {
    return call("exitFullscreen").then(() => void 0);
  },
  /** 锁住**当前**的屏幕方向(和 Telegram 一样);isOrientationLocked 跟着变 */
  lockOrientation() {
    return call("lockOrientation").then((ok) => {
      state.isOrientationLocked = ok !== false;
    });
  },
  unlockOrientation() {
    return call("unlockOrientation").then(() => {
      state.isOrientationLocked = false;
    });
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
    case "requestFullscreen":
    case "exitFullscreen":
      Promise.resolve().then(() => applyEvent("fullscreenChanged", { isFullscreen: method === "requestFullscreen" }));
      return Promise.resolve(true);
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
if (mock) state.version = PROTOCOL_VERSION;
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
function telegramVersion() {
  return versionAtLeast(state.version, "2.1") ? "8.0" : "7.10";
}
var warned = {};
function unsupported(name) {
  if (warned[name]) return;
  warned[name] = true;
  console.warn(`[SuperZ] Telegram.WebApp.${name}:超级赞里没有这项能力,按 Telegram 的「不支持」约定处理`);
}
function later(fn) {
  Promise.resolve().then(() => {
    try {
      fn();
    } catch (e) {
      setTimeout(() => {
        throw e;
      });
    }
  });
}
var callCb = (cb, ...a) => {
  if (typeof cb === "function") cb(...a);
};
function sensorStub(event, fields) {
  const s = {
    isStarted: false,
    ...fields,
    start(_params, cb) {
      unsupported(`${event}.start`);
      later(() => {
        callCb(cb, false);
        emit(`${event}Failed`, { error: "UNSUPPORTED" });
      });
      return s;
    },
    stop(cb) {
      later(() => callCb(cb, true));
      return s;
    }
  };
  return s;
}
function deviceStorageStub(name, secure) {
  const fail = (op, cb) => {
    unsupported(`${name}.${op}`);
    later(() => callCb(cb, "UNSUPPORTED", null));
  };
  const s = {
    setItem(_k, _v, cb) {
      fail("setItem", cb);
      return s;
    },
    getItem(_k, cb) {
      fail("getItem", cb);
      return s;
    },
    removeItem(_k, cb) {
      fail("removeItem", cb);
      return s;
    },
    clear(cb) {
      fail("clear", cb);
      return s;
    }
  };
  if (secure) s.restoreItem = (_k, cb) => {
    fail("restoreItem", cb);
    return s;
  };
  return s;
}
var TgCloudStorage = {
  setItem(key, value, cb) {
    CloudStorage.setItem(key, value).then(() => callCb(cb, null, true), (e) => callCb(cb, e));
    return TgCloudStorage;
  },
  getItem(key, cb) {
    CloudStorage.getItemsWithRev([key]).then((r) => {
      var _a2, _b;
      return callCb(cb, null, (_b = (_a2 = r[key]) == null ? void 0 : _a2.value) != null ? _b : "");
    }, (e) => callCb(cb, e));
    return TgCloudStorage;
  },
  getItems(keys, cb) {
    CloudStorage.getItemsWithRev(keys).then((r) => {
      var _a2, _b;
      const out = {};
      for (const k of keys) out[k] = (_b = (_a2 = r[k]) == null ? void 0 : _a2.value) != null ? _b : "";
      callCb(cb, null, out);
    }, (e) => callCb(cb, e));
    return TgCloudStorage;
  },
  removeItem(key, cb) {
    return TgCloudStorage.removeItems([key], cb);
  },
  removeItems(keys, cb) {
    CloudStorage.removeItems(keys).then(() => callCb(cb, null, true), (e) => callCb(cb, e));
    return TgCloudStorage;
  },
  getKeys(cb) {
    CloudStorage.getKeys().then((k) => callCb(cb, null, k), (e) => callCb(cb, e));
    return TgCloudStorage;
  }
};
var LocationManager = {
  isInited: false,
  isLocationAvailable: false,
  isAccessRequested: false,
  isAccessGranted: false,
  init(cb) {
    const first = !LocationManager.isInited;
    LocationManager.isInited = true;
    later(() => {
      callCb(cb);
      if (first) emit("locationManagerUpdated");
    });
    return LocationManager;
  },
  /** 没有定位:回调给 null(Telegram 在用户没授权时就是 null) */
  getLocation(cb) {
    unsupported("LocationManager.getLocation");
    later(() => callCb(cb, null));
    return LocationManager;
  },
  openSettings() {
    return LocationManager;
  }
};
var BiometricManager = {
  isInited: false,
  isBiometricAvailable: false,
  biometricType: "unknown",
  isAccessRequested: false,
  isAccessGranted: false,
  isBiometricTokenSaved: false,
  deviceId: "",
  init(cb) {
    const first = !BiometricManager.isInited;
    BiometricManager.isInited = true;
    later(() => {
      callCb(cb);
      if (first) emit("biometricManagerUpdated");
    });
    return BiometricManager;
  },
  requestAccess(_p, cb) {
    unsupported("BiometricManager.requestAccess");
    later(() => callCb(cb, false));
    return BiometricManager;
  },
  authenticate(_p, cb) {
    unsupported("BiometricManager.authenticate");
    later(() => {
      callCb(cb, false, null);
      emit("biometricAuthRequested", { isAuthenticated: false });
    });
    return BiometricManager;
  },
  updateBiometricToken(_t, cb) {
    later(() => {
      callCb(cb, false);
      emit("biometricTokenUpdated", { isUpdated: false });
    });
    return BiometricManager;
  },
  openSettings() {
    return BiometricManager;
  }
};
var tgWrapped = {};
var verticalSwipes = true;
var tgUnsafeOf = null;
var tgUnsafe = {};
function fire(p) {
  p.catch(() => void 0);
}
var TelegramWebApp = Object.create(WebApp);
Object.defineProperties(TelegramWebApp, {
  version: { get: telegramVersion, enumerable: true },
  /** initDataUnsafe 加上 Telegram 的字段名:user.id 是 open_id(字符串,按应用隔离),first_name / photo_url 是昵称头像 */
  initDataUnsafe: {
    enumerable: true,
    get() {
      var _a2;
      if (tgUnsafeOf !== state.initData) {
        tgUnsafeOf = state.initData;
        const base = { ...unsafeData() };
        if (base.user) {
          const u = base.user;
          base.user = { ...u, id: u.open_id, first_name: (_a2 = u.nickname) != null ? _a2 : "" };
          if (u.avatar_url) base.user.photo_url = u.avatar_url;
        }
        tgUnsafe = base;
      }
      return tgUnsafe;
    }
  },
  /** Telegram 的口径:安全区里面再让出的那一截(胶囊占的地方),和 safeAreaInset 相加才是总边距 */
  contentSafeAreaInset: { get: tgContentInset, enumerable: true },
  headerColor: { get: () => effectiveColor("header"), set: (v) => TelegramWebApp.setHeaderColor(v), enumerable: true },
  backgroundColor: {
    get: () => effectiveColor("background"),
    set: (v) => TelegramWebApp.setBackgroundColor(v),
    enumerable: true
  },
  bottomBarColor: {
    get: () => effectiveColor("bottomBar"),
    set: (v) => TelegramWebApp.setBottomBarColor(v),
    enumerable: true
  },
  isClosingConfirmationEnabled: {
    get: () => state.isClosingConfirmationEnabled,
    set: (v) => v ? TelegramWebApp.enableClosingConfirmation() : TelegramWebApp.disableClosingConfirmation(),
    enumerable: true
  },
  /** 超级赞的内容区本来就不会被竖着滑走,只记开关状态 */
  isVerticalSwipesEnabled: { get: () => verticalSwipes, set: (v) => {
    verticalSwipes = !!v;
  }, enumerable: true },
  isOrientationLocked: {
    get: () => state.isOrientationLocked,
    set: (v) => v ? TelegramWebApp.lockOrientation() : TelegramWebApp.unlockOrientation(),
    enumerable: true
  }
});
Object.assign(TelegramWebApp, {
  isVersionAtLeast(v) {
    return versionAtLeast(telegramVersion(), v);
  },
  onEvent(name, fn) {
    if (typeof fn !== "function") return;
    const list = tgWrapped[name] = tgWrapped[name] || [];
    if (list.some(([orig]) => orig === fn)) return;
    const wrapped = (d) => fn.call(TelegramWebApp, d);
    list.push([fn, wrapped]);
    WebApp.onEvent(name, wrapped);
  },
  offEvent(name, fn) {
    const list = tgWrapped[name] || [];
    const hit = list.find(([orig]) => orig === fn);
    if (!hit) return;
    tgWrapped[name] = list.filter((x) => x !== hit);
    WebApp.offEvent(name, hit[1]);
  },
  // ---- 和 SuperZ 一样的方法,只是按 Telegram 的约定:不返回 Promise、失败不 reject
  ready() {
    fire(WebApp.ready());
  },
  expand() {
    fire(WebApp.expand());
  },
  close() {
    fire(WebApp.close());
  },
  setHeaderColor(c) {
    fire(WebApp.setHeaderColor(c));
  },
  setBackgroundColor(c) {
    fire(WebApp.setBackgroundColor(c));
  },
  setBottomBarColor(c) {
    fire(WebApp.setBottomBarColor(c));
  },
  enableClosingConfirmation() {
    fire(WebApp.enableClosingConfirmation());
  },
  disableClosingConfirmation() {
    fire(WebApp.disableClosingConfirmation());
  },
  enableVerticalSwipes() {
    verticalSwipes = true;
  },
  disableVerticalSwipes() {
    verticalSwipes = false;
  },
  requestFullscreen() {
    fire(WebApp.requestFullscreen());
  },
  exitFullscreen() {
    fire(WebApp.exitFullscreen());
  },
  lockOrientation() {
    fire(WebApp.lockOrientation());
  },
  unlockOrientation() {
    fire(WebApp.unlockOrientation());
  },
  /** options(try_instant_view、try_browser)收下不用:超级赞一律先问「即将离开超级赞」再交系统浏览器 */
  openLink(url, _options) {
    fire(WebApp.openLink(String(url)));
  },
  /** 弹不出来(没有能力、参数不对、不在宿主里)按「没点任何按钮就关了」回 null,和用户点空白关掉一样 */
  showPopup(params, cb) {
    showPopup(params).then((id) => callCb(cb, id), () => callCb(cb, null));
  },
  showAlert(message, cb) {
    showPopup({ message, buttons: [{ type: "close" }] }).then(() => callCb(cb), () => callCb(cb));
  },
  showConfirm(message, cb) {
    showPopup({ message, buttons: [{ id: "ok", type: "ok" }, { type: "cancel" }] }).then((id) => callCb(cb, id === "ok"), () => callCb(cb, false));
  },
  CloudStorage: TgCloudStorage,
  DeviceStorage: deviceStorageStub("DeviceStorage", false),
  SecureStorage: deviceStorageStub("SecureStorage", true),
  BiometricManager,
  LocationManager,
  Accelerometer: sensorStub("accelerometer", { x: null, y: null, z: null }),
  DeviceOrientation: sensorStub("deviceOrientation", { absolute: false, alpha: null, beta: null, gamma: null }),
  Gyroscope: sensorStub("gyroscope", { x: null, y: null, z: null }),
  // ---- 超级赞没有的:不抛、不报 undefined,按 Telegram 的回调 / 事件约定回「不支持」
  sendData(_data) {
    unsupported("sendData");
  },
  switchInlineQuery(_query, _types) {
    unsupported("switchInlineQuery");
  },
  openTelegramLink(_url, _options) {
    unsupported("openTelegramLink");
  },
  /** 收款:本期不允许。回 'failed' 并发 invoiceClosed,付款流程走不下去 */
  openInvoice(url, cb) {
    unsupported("openInvoice");
    later(() => {
      callCb(cb, "failed");
      emit("invoiceClosed", { url, status: "failed" });
    });
  },
  shareToStory(_mediaUrl, _params) {
    unsupported("shareToStory");
  },
  shareMessage(_id, cb) {
    unsupported("shareMessage");
    later(() => {
      callCb(cb, false);
      emit("shareMessageFailed", { error: "UNSUPPORTED" });
    });
  },
  setEmojiStatus(_id, params, cb) {
    if (typeof params === "function") cb = params;
    unsupported("setEmojiStatus");
    later(() => {
      callCb(cb, false);
      emit("emojiStatusFailed", { error: "UNSUPPORTED" });
    });
  },
  requestEmojiStatusAccess(cb) {
    unsupported("requestEmojiStatusAccess");
    later(() => {
      callCb(cb, false);
      emit("emojiStatusAccessRequested", { status: "cancelled" });
    });
  },
  downloadFile(_params, cb) {
    unsupported("downloadFile");
    later(() => {
      callCb(cb, false);
      emit("fileDownloadRequested", { status: "cancelled" });
    });
  },
  addToHomeScreen() {
    unsupported("addToHomeScreen");
  },
  checkHomeScreenStatus(cb) {
    later(() => {
      callCb(cb, "unsupported");
      emit("homeScreenChecked", { status: "unsupported" });
    });
  },
  /** 扫码:按「用户把扫码框关了」回 —— 只发 scanQrPopupClosed,回调不会被调 */
  showScanQrPopup(_params, _cb) {
    unsupported("showScanQrPopup");
    later(() => emit("scanQrPopupClosed"));
  },
  closeScanQrPopup() {
  },
  readTextFromClipboard(cb) {
    unsupported("readTextFromClipboard");
    later(() => {
      callCb(cb, null);
      emit("clipboardTextReceived", { data: null });
    });
  },
  requestWriteAccess(cb) {
    unsupported("requestWriteAccess");
    later(() => {
      callCb(cb, false);
      emit("writeAccessRequested", { status: "cancelled" });
    });
  },
  requestContact(cb) {
    unsupported("requestContact");
    later(() => {
      callCb(cb, false, { status: "cancelled" });
      emit("contactRequested", { status: "cancelled" });
    });
  },
  requestChat(_reqId, cb) {
    unsupported("requestChat");
    later(() => {
      callCb(cb, false);
      emit("requestedChatFailed", { error: "UNSUPPORTED" });
    });
  },
  invokeCustomMethod(_method, _params, cb) {
    unsupported("invokeCustomMethod");
    later(() => callCb(cb, "UNSUPPORTED", null));
  },
  /** 收起软键盘:页面里当前的输入框失焦就行,不用宿主 */
  hideKeyboard() {
    var _a2, _b, _c;
    try {
      (_c = (_b = (_a2 = w.document) == null ? void 0 : _a2.activeElement) == null ? void 0 : _b.blur) == null ? void 0 : _c.call(_b);
    } catch (_) {
    }
  }
});
w.SuperZ = w.SuperZ || {};
w.SuperZ.WebApp = WebApp;
w.Telegram = w.Telegram || {};
if (!w.Telegram.WebApp) w.Telegram.WebApp = TelegramWebApp;
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
  TelegramWebApp,
  WebApp,
  src_default as default
};
