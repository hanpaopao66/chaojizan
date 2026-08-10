import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/**
 * 推送通道。
 *
 * ## 为什么这是商家端最重要的一个文件
 *
 * 安卓端靠前台服务把进程钉住,做到「锁屏不丢单」。**鸿蒙不给这条路**:
 * 长时任务只认 dataTransfer / audioPlayback / audioRecording / location /
 * bluetoothInteraction / multiDeviceConnection / voip
 * (taskKeeping 只给 2in1,wifiInteraction 只给系统应用),
 * 「听订单」一种都不沾。
 *
 * 声明 audioPlayback 再播静音音频保活是钻空子:系统会校验声明的模式和
 * 实际行为是否一致,上架审核这一条也是明写的。更要命的是**它不可靠** ——
 * 拿一个随时可能被收走的机制去兑现「锁屏不丢单」,等于在午高峰押注。
 *
 * 所以鸿蒙商家端的口径是:
 *
 * ```
 * 应用在前台 → WebSocket 实时推 + 语音催单 + 屏幕常亮
 * 应用在后台 → 系统通知(推送),商家点通知回到应用
 * 回到前台   → 立刻全量拉一次,补上后台期间漏掉的
 * ```
 *
 * 服务端**本来就是这么设计的** —— `server/app/services/push.py` 里
 * `notify_new_order` 的注释原话:「新订单推给商家老板(离线也能听到,
 * 替代只在前台有效的 WebSocket)」。安卓端的前台服务是锦上添花。
 *
 * ## 绑定方式:别名,不是 token 上报
 *
 * 三端一致走极光(JPush),**绑定在 SDK 侧做** —— 登录后
 * `setAlias('u{userId}')`,服务端按这个别名定向推
 * (见 `server/app/services/push.py` 的 `audience: {alias: [...]}`)。
 *
 * 所以**我们服务端没有、也不需要收 token 的接口**。
 * 安卓端 `packages/shared/lib/src/push_service.dart` 就是这么做的,
 * 鸿蒙端照搬同一套约定,别自作主张加一条上报链路。
 *
 * ## ⚠️ 现在是空实现,等开发者账号
 *
 * 极光的鸿蒙 SDK 最终骑在华为 Push Kit 上,要:
 * AppGallery Connect 注册应用 → 拿 Push 的 Client ID →
 * 申请通知消息的**自分类权益**(不申请就落进默认分类,响不响、
 * 会不会被免打扰拦掉都不由我们说了算)→ 服务端 `push.py` 补鸿蒙那一段。
 *
 * 这一层**故意抽成接口**,所以:
 *
 * - 上层(Listen.ets、通知点击跳转)现在就能写完、能测;
 * - SDK 到位后只补一个 `JPushProvider implements PushProvider`,别的不动;
 * - **不会出现「等 SDK 到了再从头设计」** —— 那时改的就是架构了。
 */

/** 一条推送带过来的负载。对应服务端 `extras` 那一坨 */
export interface PushPayload {
  /** new_order / bad_review / urge */
  type?: string;
  order_no?: string;
  summary?: string;
}

/**
 * 推送 SDK 的抽象。真实现和空实现都满足它。
 *
 * 三个方法**都不许把异常抛到上层** —— 推送用不了是「少一条通道」,
 * 不是「这个应用不能用了」。商家照样能在前台接单。
 */
export interface PushProvider {
  /** 应用启动时叫一次。返回是否可用 */
  setup(): Promise<boolean>;

  /** 登录后绑别名。服务端按 `u{userId}` 定向推 */
  bindUser(userId: number): Promise<void>;

  /** 退出登录时解绑,防止推送发给已登出的设备 */
  unbind(): Promise<void>;
}

/**
 * 空实现:开发者账号下来之前用它。
 *
 * `setup` 返回 false 而不是抛异常,也**不假装成功** —— 假装更坏:
 * 界面会显示「推送已开启」,而商家锁屏之后一单都收不到,
 * 等他发现的时候已经丢了一天的单。
 */
export class NoopPushProvider implements PushProvider {
  async setup(): Promise<boolean> {
    hilog.info(DOMAIN, TAG, '推送 SDK 未接入,后台通道不可用');
    return false;
  }

  async bindUser(_userId: number): Promise<void> {
  }

  async unbind(): Promise<void> {
  }
}

/**
 * 推送通道的门面。上层只跟它打交道,不认识具体 SDK。
 */
export class PushChannel {
  private static provider: PushProvider = new NoopPushProvider();
  private static ok: boolean = false;

  /** 换成真实现。SDK 到位后在 EntryAbility 里叫一次 */
  static use(provider: PushProvider): void {
    PushChannel.provider = provider;
  }

  /**
   * 后台通道到底能不能用。
   *
   * **界面上要照实说**:能用就说「锁屏也能收到新单」,
   * 不能用就说「应用退到后台可能收不到新单,请保持应用在前台」。
   * 含糊其辞的后果是商家按前者的预期用,按后者的现实丢单。
   */
  static get ready(): boolean {
    return PushChannel.ok;
  }

  static async setup(): Promise<void> {
    try {
      PushChannel.ok = await PushChannel.provider.setup();
    } catch (e) {
      PushChannel.ok = false;
      hilog.warn(DOMAIN, TAG, '推送初始化失败 %{public}s', JSON.stringify(e));
    }
  }

  /**
   * 登录后绑别名。
   *
   * 失败静默 —— 前台听单不受影响,而这时候弹一个「推送注册失败」
   * 除了让商家焦虑之外没有任何用,他也没法处理。
   * 真要让他知道,是在设置页显示一行状态(见 [ready])。
   */
  static async bindUser(userId: number): Promise<void> {
    if (!PushChannel.ok) {
      return;
    }
    try {
      await PushChannel.provider.bindUser(userId);
    } catch (e) {
      hilog.warn(DOMAIN, TAG, '绑定别名失败 %{public}s', JSON.stringify(e));
    }
  }

  static async unbind(): Promise<void> {
    if (!PushChannel.ok) {
      return;
    }
    try {
      await PushChannel.provider.unbind();
    } catch (e) {
      hilog.warn(DOMAIN, TAG, '解绑失败 %{public}s', JSON.stringify(e));
    }
  }

  /**
   * 从冷启动/热启动的 want 参数里把推送负载抠出来。
   *
   * **这段和 SDK 无关,现在就能写完、就能测。** 商家点通知进来,
   * 必须直接落到那一单 —— 落到订单列表让他自己找,等于白推。
   */
  static payloadOf(params: Record<string, Object> | undefined):
      PushPayload | null {
    if (params === undefined) {
      return null;
    }
    const orderNo: Object | undefined = params['order_no'];
    const type: Object | undefined = params['type'];
    if (orderNo === undefined && type === undefined) {
      return null;
    }
    const summary: Object | undefined = params['summary'];
    return {
      type: type === undefined ? undefined : `${type}`,
      order_no: orderNo === undefined ? undefined : `${orderNo}`,
      summary: summary === undefined ? undefined : `${summary}`,
    };
  }
}
