/*!
 * 超级赞小程序 SDK v2 —— window.SuperZ.WebApp(DEV-PROMPTS-39 §5.4、#323)
 *
 * 用法:托管页在 <head> 里同源引一份(每个托管 origin 下都有):
 *
 *   <script src="/_sdk/2/sz-webapp.js"></script>
 *   <script>
 *     const app = SuperZ.WebApp
 *     app.ready()
 *     fetch('https://你的后端/login', {method: 'POST', body: app.initData})  // 后端验签
 *   </script>
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
export declare const SDK_VERSION = "2.0.0";
export type ColorScheme = 'light' | 'dark';
export type Platform = 'android' | 'ios' | 'web' | 'unknown';
export interface ThemeParams {
    bg_color?: string;
    secondary_bg_color?: string;
    text_color?: string;
    hint_color?: string;
    link_color?: string;
    button_color?: string;
    button_text_color?: string;
    accent_text_color?: string;
    destructive_text_color?: string;
    line_color?: string;
}
export interface SafeAreaInset {
    top: number;
    bottom: number;
    left: number;
    right: number;
}
export interface WebAppUser {
    open_id: string;
    language_code?: string;
    /** 用户同意过 requestProfile 的应用才有 */
    nickname?: string;
    avatar_url?: string;
}
export interface InitDataUnsafe {
    app_id?: string;
    auth_date?: number;
    launch_id?: string;
    user?: WebAppUser;
    start_param?: string;
    /** 模拟器启动时是 'sim':你的后端应据此区分测试流量 */
    env?: string;
    sig_kid?: string;
    hash?: string;
    signature?: string;
}
export interface PopupButton {
    id?: string;
    type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive';
    text?: string;
}
export interface PopupParams {
    title?: string;
    message: string;
    buttons?: PopupButton[];
}
export interface BottomButtonParams {
    text?: string;
    color?: string;
    text_color?: string;
    is_visible?: boolean;
    is_active?: boolean;
    is_progress_visible?: boolean;
    /** 只有 SecondaryButton 用:相对主按钮的位置 */
    position?: 'left' | 'right' | 'top' | 'bottom';
}
export interface StoredItem {
    value: string;
    rev: number;
}
export type EventName = 'themeChanged' | 'viewportChanged' | 'safeAreaChanged' | 'contentSafeAreaChanged' | 'mainButtonClicked' | 'secondaryButtonClicked' | 'backButtonClicked' | 'settingsButtonClicked' | 'popupClosed' | 'activated' | 'deactivated' | 'fullscreenChanged' | 'fullscreenFailed';
/** 桥错误码(§5.4)。页面按 code 判断,不按 message —— message 会改措辞,code 不会。 */
export declare const ERRORS: {
    readonly CAPABILITY_NOT_GRANTED: 4001;
    readonly USER_DENIED: 4002;
    readonly NOT_SUPPORTED: 4003;
    readonly INVALID_PARAMS: 4004;
    readonly RATE_LIMITED: 4005;
    readonly QUOTA_EXCEEDED: 4006;
    readonly REV_CONFLICT: 4007;
    readonly NOT_IN_HOST: 4008;
    readonly APP_SUSPENDED: 4009;
    readonly INTERNAL: 5000;
    readonly NETWORK: 5001;
};
export declare class SzError extends Error {
    code: number;
    constructor(code: number, message: string);
}
/** 线上的方法名(宿主的分发表按它注册;文档参考页由 scripts/check_sdk_docs.mjs 对照) */
export declare const BRIDGE_METHODS: readonly ["ready", "expand", "close", "setHeaderColor", "setBackgroundColor", "setClosingConfirmation", "mainButton", "secondaryButton", "backButton", "settingsButton", "haptic", "showPopup", "openLink", "share", "CloudStorage.getItems", "CloudStorage.setItem", "CloudStorage.removeItems", "CloudStorage.getKeys", "requestFullscreen", "exitFullscreen", "lockOrientation", "unlockOrientation", "requestProfile", "legacy.getInitData"];
type Listener = (data?: any) => void;
declare class BottomButton {
    private method;
    text: string;
    color: string;
    textColor: string;
    isVisible: boolean;
    isActive: boolean;
    isProgressVisible: boolean;
    position: BottomButtonParams['position'];
    private handlers;
    private scheduled;
    constructor(method: 'mainButton' | 'secondaryButton', text: string);
    /** @internal */
    _fire(): void;
    private _sync;
    setText(text: string): this;
    show(): this;
    hide(): this;
    enable(): this;
    disable(): this;
    showProgress(_leaveActive?: boolean): this;
    hideProgress(): this;
    setParams(p: BottomButtonParams): this;
    onClick(fn: Listener): this;
    offClick(fn: Listener): this;
}
declare class HeaderButton {
    private method;
    isVisible: boolean;
    private handlers;
    constructor(method: 'backButton' | 'settingsButton');
    /** @internal */
    _fire(): void;
    show(): this;
    hide(): this;
    onClick(fn: Listener): this;
    offClick(fn: Listener): this;
}
declare function showPopup(params: PopupParams, cb?: (buttonId: string | null) => void): Promise<string | null>;
export declare const WebApp: {
    readonly version: string;
    sdkVersion: string;
    readonly platform: Platform;
    readonly colorScheme: ColorScheme;
    readonly themeParams: ThemeParams;
    /** 原样交给你的后端验签。**不要**在前端信任它的内容 —— 用 initDataUnsafe 只做展示 */
    readonly initData: string;
    readonly initDataUnsafe: InitDataUnsafe;
    readonly inHost: boolean;
    readonly isMock: boolean;
    readonly isExpanded: boolean;
    readonly isFullscreen: boolean;
    readonly isActive: boolean;
    readonly viewportHeight: any;
    readonly viewportStableHeight: any;
    readonly safeAreaInset: SafeAreaInset;
    readonly contentSafeAreaInset: SafeAreaInset;
    readonly isClosingConfirmationEnabled: boolean;
    readonly headerColor: string;
    readonly backgroundColor: string;
    /** 宿主给这个应用开了哪些能力(basic 之外的要在开发者后台申请) */
    readonly capabilities: string[];
    startParam(): string;
    isVersionAtLeast(v: string): boolean;
    ready(): Promise<void>;
    expand(): Promise<void>;
    close(): Promise<void>;
    setHeaderColor(color: string): Promise<void>;
    setBackgroundColor(color: string): Promise<void>;
    enableClosingConfirmation(): Promise<void>;
    disableClosingConfirmation(): Promise<void>;
    onEvent(name: EventName, fn: Listener): void;
    offEvent(name: EventName, fn: Listener): void;
    showPopup: typeof showPopup;
    showAlert(message: string, cb?: () => void): Promise<void>;
    showConfirm(message: string, cb?: (ok: boolean) => void): Promise<boolean>;
    /** 在系统浏览器打开(宿主先弹「即将离开超级赞」) */
    openLink(url: string): Promise<void>;
    /** 系统分享面板。url 可省(默认分享这个小程序的直达链接) */
    share(p: {
        text: string;
        url?: string;
    }): Promise<boolean>;
    requestFullscreen(): Promise<void>;
    exitFullscreen(): Promise<void>;
    lockOrientation(): Promise<void>;
    unlockOrientation(): Promise<void>;
    /**
     * 请求昵称和头像(要申请 profile 能力;首次宿主会弹确认,用户可在设置里撤回)。
     * 同意后当场拿到一份**新签发的** initData —— 把它交给你的后端验签,页面自己报的昵称不可信。
     */
    requestProfile(cb?: (e: any, r?: {
        initData: string;
        user?: WebAppUser;
    }) => void): Promise<{
        initData: string;
        user?: WebAppUser;
    }>;
    MainButton: BottomButton;
    SecondaryButton: BottomButton;
    BackButton: HeaderButton;
    SettingsButton: HeaderButton;
    HapticFeedback: {
        impactOccurred(style?: "light" | "medium" | "heavy" | "rigid" | "soft"): /*elided*/ any;
        notificationOccurred(type?: "error" | "success" | "warning"): /*elided*/ any;
        selectionChanged(): /*elided*/ any;
    };
    CloudStorage: {
        /** 写一个键。带 ifRev 时版本不符回 4007(REV_CONFLICT);ifRev=0 表示「必须还不存在」 */
        setItem(key: string, value: string, opts?: {
            ifRev?: number;
        } | ((e: any, r?: any) => void), cb?: (e: any, r?: {
            key: string;
            rev: number;
        }) => void): Promise<{
            key: string;
            rev: number;
        }>;
        getItem(key: string, cb?: (e: any, v?: string | null) => void): Promise<string | null>;
        getItems(keys: string[], cb?: (e: any, v?: Record<string, string | null>) => void): Promise<Record<string, string | null>>;
        /** 带版本号读(做 ifRev 并发控制时用)。一次最多 100 个键 */
        getItemsWithRev(keys: string[]): Promise<Record<string, StoredItem | null>>;
        removeItem(key: string, cb?: (e: any, ok?: boolean) => void): Promise<boolean>;
        removeItems(keys: string[], cb?: (e: any, ok?: boolean) => void): Promise<boolean>;
        /** 列键。prefix 可选;超过 limit 时用返回的 next_cursor 翻页 */
        getKeys(opts?: {
            prefix?: string;
            cursor?: string;
            limit?: number;
        } | ((e: any, k?: string[]) => void), cb?: (e: any, k?: string[]) => void): Promise<string[]>;
        getKeysPage(o?: {
            prefix?: string;
            cursor?: string;
            limit?: number;
        }): Promise<{
            keys: string[];
            next_cursor: string | null;
        }>;
    };
    ERRORS: {
        readonly CAPABILITY_NOT_GRANTED: 4001;
        readonly USER_DENIED: 4002;
        readonly NOT_SUPPORTED: 4003;
        readonly INVALID_PARAMS: 4004;
        readonly RATE_LIMITED: 4005;
        readonly QUOTA_EXCEEDED: 4006;
        readonly REV_CONFLICT: 4007;
        readonly NOT_IN_HOST: 4008;
        readonly APP_SUSPENDED: 4009;
        readonly INTERNAL: 5000;
        readonly NETWORK: 5001;
    };
    SzError: typeof SzError;
};
export type WebAppType = typeof WebApp;
export default WebApp;
