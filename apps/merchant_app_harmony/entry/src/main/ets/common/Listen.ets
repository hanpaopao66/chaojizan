import { webSocket } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Session } from './Session';
import { PushChannel } from './PushChannel';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/** WebSocket 推过来的一条消息 */
export interface ListenEvent {
  /** new_order / bad_review / urge */
  type: string;
  order_no?: string;
  summary?: string;
  total_cents?: number;
  rating?: number;
}

/** 听单通道当前的状态。**顶部那盏灯照实显示这个** */
export enum ListenState {
  /** 前台 + WebSocket 连着 + 列表新鲜:一切正常 */
  LIVE = 0,
  /** 应用在后台,靠推送。**这是正常状态,不是故障** */
  BACKGROUND = 1,
  /** 前台但 WebSocket 断了,正在重连。轮询在兜底 */
  RECONNECTING = 2,
  /** 出问题了:列表拉不到,或者后台没有推送通道 */
  BROKEN = 3,
}

/**
 * 听单。
 *
 * ## 架构
 *
 * 安卓端靠前台服务保活,鸿蒙不给这条路(理由见 PushChannel.ets)。口径是:
 *
 * ```
 * 前台 → WebSocket 实时 + 15 秒轮询兜底 + 语音催单 + 屏幕常亮
 * 后台 → 系统通知(推送)
 * 回前台 → 立刻全量拉一次,补上后台期间漏掉的
 * ```
 *
 * ## 三条不许破的规矩
 *
 * 1. **回前台必须主动全量拉一次**,不能只依赖 WebSocket 补发。
 *    息屏那段时间连接早断了,重连之后服务端不会把断线期间的消息补给你;
 * 2. **拉失败不清空订单列表**。保留上一次的结果比变成空列表安全 ——
 *    空列表和「今天没单」长得一模一样,而商家会照着它去休息;
 * 3. **指示灯的口径是「WebSocket 连着 + 列表新鲜」两者都好**。
 *    只看 WebSocket 会出现"灯是绿的、列表是空的"这种最误导人的组合。
 *    安卓端为此翻过车,见 DEV-PROMPTS-27 #237。
 */
export class Listen {
  private ws: webSocket.WebSocket | null = null;
  private pingTimer: number = -1;
  private pollTimer: number = -1;
  private reconnectTimer: number = -1;
  private connected: boolean = false;
  private foreground: boolean = true;

  /** 最后一次**成功拉到订单列表**的时刻。0 = 一次都没成功过 */
  private lastOkAt: number = 0;
  /** 最后一次拉取的错误。非空 = 上一次失败了 */
  private lastError: string = '';

  private shopId: number = 0;
  private baseUrl: string = '';

  /** 收到实时消息。页面挂上去 */
  onEvent: ((e: ListenEvent) => void) | null = null;
  /** 该重新拉列表了(轮询到点、WebSocket 报新单、回到前台) */
  onRefresh: (() => void) | null = null;
  /** 状态变了,刷新那盏灯 */
  onStateChange: ((s: ListenState) => void) | null = null;

  /** 轮询间隔。WebSocket 断线期间靠它兜底,所以不能太长 */
  private static readonly POLL_MS: number = 15000;
  private static readonly PING_MS: number = 30000;
  private static readonly RECONNECT_MS: number = 5000;
  /** 超过这个时间没成功拉到列表就算「陈了」。轮询 15 秒一次,连挂 4 次 */
  private static readonly STALE_MS: number = 60000;

  start(baseUrl: string, shopId: number): void {
    this.baseUrl = baseUrl;
    this.shopId = shopId;
    this.connect();
    this.startPolling();
  }

  stop(): void {
    this.clearTimer(this.pingTimer);
    this.clearTimer(this.pollTimer);
    this.clearTimer(this.reconnectTimer);
    this.pingTimer = -1;
    this.pollTimer = -1;
    this.reconnectTimer = -1;
    this.closeWs();
  }

  /**
   * 切店。
   *
   * ⚠️ 调用方**必须同时**换掉 `MerchantApi.shopId`、营业开关、今日营业额、
   * 订单列表。漏掉任何一处就是「切到二店,屏幕上还是总店的单」,
   * 而商家会照着总店的单去二店备餐。
   */
  switchShop(shopId: number): void {
    if (this.shopId === shopId) {
      return;
    }
    this.shopId = shopId;
    this.lastOkAt = 0;
    this.lastError = '';
    this.closeWs();
    this.connect();
    this.emitState();
  }

  // ---------- 前后台 ----------

  /**
   * 回到前台。EntryAbility.onForeground 里叫。
   *
   * **立刻全量拉一次**是这里最要紧的一行:息屏期间 WebSocket 早断了,
   * 重连之后服务端不会补发断线期间的消息。不主动拉,商家看到的就是
   * 一份停在他锁屏那一刻的订单列表。
   */
  onForeground(): void {
    this.foreground = true;
    this.connect();
    this.startPolling();
    if (this.onRefresh !== null) {
      this.onRefresh();
    }
    this.emitState();
  }

  /**
   * 退到后台。
   *
   * 把 WebSocket 和轮询都停掉 —— **不是为了省电,是因为留着也没用**:
   * 鸿蒙不给后台保活,进程随时会被挂起,留着的连接只是个死握把。
   * 这段时间靠推送。
   */
  onBackground(): void {
    this.foreground = false;
    this.clearTimer(this.pollTimer);
    this.pollTimer = -1;
    this.closeWs();
    this.emitState();
  }

  // ---------- 列表新鲜度 ----------

  /** 订单列表拉成功了。页面每次拉完叫一次 */
  markOrdersOk(): void {
    this.lastOkAt = Date.now();
    this.lastError = '';
    this.emitState();
  }

  /** 订单列表拉失败了。**别偷偷咽下去** */
  markOrdersFailed(message: string): void {
    this.lastError = message;
    this.emitState();
  }

  /** 列表是不是「陈」了 */
  get ordersStale(): boolean {
    if (this.lastOkAt === 0) {
      return this.lastError.length > 0; // 首次就失败
    }
    return Date.now() - this.lastOkAt > Listen.STALE_MS;
  }

  get state(): ListenState {
    if (!this.foreground) {
      // 后台:有推送通道就是正常,没有就是真收不到
      return PushChannel.ready ? ListenState.BACKGROUND : ListenState.BROKEN;
    }
    if (this.ordersStale) {
      return ListenState.BROKEN;
    }
    return this.connected ? ListenState.LIVE : ListenState.RECONNECTING;
  }

  /** 那盏灯旁边的一句话。**照实说,不许含糊** */
  get stateText(): string {
    switch (this.state) {
      case ListenState.LIVE:
        return '实时听单中';
      case ListenState.BACKGROUND:
        return '应用在后台,新单会推送提醒';
      case ListenState.RECONNECTING:
        return '连接断了,正在重连(仍在轮询)';
      default:
        return PushChannel.ready
            ? '订单列表没更新成功,可能有新单没显示'
            : '应用退到后台可能收不到新单,请保持应用在前台';
    }
  }

  // ---------- 内部 ----------

  private emitState(): void {
    if (this.onStateChange !== null) {
      this.onStateChange(this.state);
    }
  }

  private startPolling(): void {
    this.clearTimer(this.pollTimer);
    // 轮询保底:WebSocket 断线期间也不会漏单
    this.pollTimer = setInterval(() => {
      if (this.foreground && this.onRefresh !== null) {
        this.onRefresh();
      }
    }, Listen.POLL_MS);
  }

  private clearTimer(id: number): void {
    if (id >= 0) {
      clearInterval(id);
    }
  }

  private closeWs(): void {
    this.clearTimer(this.pingTimer);
    this.pingTimer = -1;
    const ws: webSocket.WebSocket | null = this.ws;
    this.ws = null;
    this.connected = false;
    if (ws === null) {
      return;
    }
    try {
      ws.close();
    } catch (_) {
      // 已经断了也会抛。目的只是把连接清干净,断不成功不影响下次新建
    }
  }

  private connect(): void {
    if (!this.foreground || this.ws !== null) {
      return;
    }
    const token: string = Session.get().token;
    if (token.length === 0 || this.shopId <= 0) {
      return;
    }
    // http(s) → ws(s)
    const wsBase: string = this.baseUrl.replace('https://', 'wss://')
        .replace('http://', 'ws://');
    const url: string = `${wsBase}/ws/merchants/${this.shopId}?token=${token}`;

    const ws: webSocket.WebSocket = webSocket.createWebSocket();
    this.ws = ws;

    ws.on('open', () => {
      this.connected = true;
      this.emitState();
      this.clearTimer(this.pingTimer);
      this.pingTimer = setInterval(() => {
        try {
          ws.send('ping');
        } catch (_) {
          // 发不出去说明连接已经废了,下面的 close 回调会安排重连
        }
      }, Listen.PING_MS);
    });

    ws.on('message', (_err: BusinessError, value: string | ArrayBuffer) => {
      if (typeof value !== 'string') {
        return;
      }
      this.handleMessage(value);
    });

    ws.on('close', () => {
      this.scheduleReconnect();
    });

    ws.on('error', () => {
      this.scheduleReconnect();
    });

    ws.connect(url, (err: BusinessError) => {
      if (err !== null && err !== undefined && err.code !== 0) {
        hilog.warn(DOMAIN, TAG, '听单连接失败 %{public}s', JSON.stringify(err));
        this.scheduleReconnect();
      }
    });
  }

  private handleMessage(raw: string): void {
    if (raw === 'pong') {
      return;
    }
    let e: ListenEvent;
    try {
      e = JSON.parse(raw) as ListenEvent;
    } catch (_) {
      hilog.warn(DOMAIN, TAG, '听单收到非 JSON 消息');
      return;
    }
    if (!this.connected) {
      this.connected = true;
      this.emitState();
    }
    if (this.onEvent !== null) {
      this.onEvent(e);
    }
    // 新单/催单都要立刻重拉列表 —— 消息本身只带摘要,详情要从接口取
    if (e.type === 'new_order' || e.type === 'urge') {
      if (this.onRefresh !== null) {
        this.onRefresh();
      }
    }
  }

  private scheduleReconnect(): void {
    this.closeWs();
    this.emitState();
    if (!this.foreground) {
      return; // 后台不重连,回前台时统一处理
    }
    this.clearTimer(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, Listen.RECONNECT_MS);
  }
}
