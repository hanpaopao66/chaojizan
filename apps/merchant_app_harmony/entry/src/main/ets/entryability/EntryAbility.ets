import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { PushChannel, PushPayload } from '../common/PushChannel';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/**
 * 应用入口。
 *
 * 这里**只做窗口加载和前后台转发,不做任何网络请求、不初始化任何收集类
 * SDK**。推送要等用户在隐私门里点了同意之后才能起 —— 同意前发一个请求
 * 就算「未经同意收集」,是工信部通报和商店驳回的头号事由。
 *
 * ## 前后台是商家端的关键路径,不是可有可无的生命周期回调
 *
 * 鸿蒙不给后台保活(理由见 common/PushChannel.ets),所以:
 *
 * - `onForeground` → 重连 WebSocket + **立刻全量拉一次订单**;
 * - `onBackground` → 停掉连接和轮询,交给推送。
 *
 * 这两个回调转发到 [AppEvents],由订单页订阅。**不能让订单页自己去
 * 监听生命周期** —— 它是个 Component,拿不到 Ability 的回调。
 */

/** 前后台与推送点击的转发站。订单页在 aboutToAppear 里订阅 */
export class AppEvents {
  static onForeground: (() => void) | null = null;
  static onBackground: (() => void) | null = null;
  /** 点通知进来要落到哪一单。页面还没起来时先存着,起来了再消费 */
  static pendingPush: PushPayload | null = null;
  static onPush: ((p: PushPayload) => void) | null = null;

  /**
   * 收到一条推送点击。
   *
   * 页面已经起来了就直接送过去;没起来先存着 —— 冷启动时 Ability 的
   * onCreate 比页面早,这时候直接派发会丢。商家点了通知却落在订单列表上,
   * 等于白推。
   */
  static deliverPush(p: PushPayload | null): void {
    if (p === null) {
      return;
    }
    if (AppEvents.onPush !== null) {
      AppEvents.onPush(p);
    } else {
      AppEvents.pendingPush = p;
    }
  }

  /** 页面挂上监听后叫一次,把存着的那条消费掉 */
  static drainPush(): void {
    const p: PushPayload | null = AppEvents.pendingPush;
    AppEvents.pendingPush = null;
    if (p !== null && AppEvents.onPush !== null) {
      AppEvents.onPush(p);
    }
  }
}

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, _launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(DOMAIN, TAG, 'EntryAbility onCreate');
    // 冷启动:点通知进来的
    AppEvents.deliverPush(PushChannel.payloadOf(want.parameters));
  }

  /** 应用已在后台,点通知把它拉回前台走这里 */
  onNewWant(want: Want, _launchParam: AbilityConstant.LaunchParam): void {
    AppEvents.deliverPush(PushChannel.payloadOf(want.parameters));
  }

  onDestroy(): void {
    hilog.info(DOMAIN, TAG, 'EntryAbility onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(DOMAIN, TAG, 'loadContent 失败: %{public}s',
            JSON.stringify(err));
        return;
      }
      hilog.info(DOMAIN, TAG, 'loadContent 成功');
    });
  }

  onWindowStageDestroy(): void {
    hilog.info(DOMAIN, TAG, 'onWindowStageDestroy');
  }

  onForeground(): void {
    hilog.info(DOMAIN, TAG, 'onForeground');
    if (AppEvents.onForeground !== null) {
      AppEvents.onForeground();
    }
  }

  onBackground(): void {
    hilog.info(DOMAIN, TAG, 'onBackground');
    if (AppEvents.onBackground !== null) {
      AppEvents.onBackground();
    }
  }
}
