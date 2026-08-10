import { media } from '@kit.MediaKit';
import { vibrator } from '@kit.SensorServiceKit';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/** 打包在 rawfile 里的提示音 */
const SOUND: string = 'new_order.m4a';

/**
 * 新单语音催单。
 *
 * ## 为什么是「持续」而不是「响一声」
 *
 * 后厨有油烟机、有抽风、有人说话。响一声很可能没人听见,而没人听见的
 * 后果是这一单超时、顾客投诉、商家挨罚。所以安卓端的口径是:
 * **只要还有待接单的单,每 10 秒响一次,直到商家处理**。鸿蒙照搬。
 *
 * ## 播放失败要退回振动
 *
 * 音频起不来的原因很多(音频焦点被抢、文件损坏、系统限制)。
 * **至少要有一个物理提示** —— 手机放在柜台上震一下,总比彻底没反应强。
 */
export class Announcer {
  private player: media.AVPlayer | null = null;
  private ctx: common.UIAbilityContext | null = null;
  private preparing: boolean = false;

  init(ctx: common.UIAbilityContext): void {
    this.ctx = ctx;
  }

  /**
   * 响一次。
   *
   * 上一遍没播完就来了新单:**重头播,不叠音** —— 两遍语音叠在一起
   * 谁也听不清,反而不如一遍。
   */
  async announce(): Promise<void> {
    this.buzz();
    try {
      await this.play();
    } catch (e) {
      hilog.warn(DOMAIN, TAG, '语音播报失败 %{public}s', JSON.stringify(e));
      // 已经震过了,这里不用再补 —— buzz 在最前面就是为了这个
    }
  }

  private buzz(): void {
    try {
      vibrator.startVibration(
          { type: 'time', duration: 500 },
          { usage: 'notification' },
          (err: Error) => {
            if (err) {
              hilog.debug(DOMAIN, TAG, '振动不可用');
            }
          });
    } catch (_) {
      // 有些设备没有马达。不影响主流程
    }
  }

  private async play(): Promise<void> {
    const ctx: common.UIAbilityContext | null = this.ctx;
    if (ctx === null) {
      return;
    }
    if (this.preparing) {
      return; // 正在准备上一次的播放,别并发建两个 player
    }
    this.preparing = true;
    try {
      await this.release();
      const player: media.AVPlayer = await media.createAVPlayer();
      this.player = player;
      player.on('stateChange', (state: string) => {
        if (state === 'initialized') {
          player.prepare();
        } else if (state === 'prepared') {
          player.play();
        } else if (state === 'completed') {
          this.release();
        }
      });
      player.on('error', () => {
        this.release();
      });
      const fd = await ctx.resourceManager.getRawFd(SOUND);
      player.fdSrc = { fd: fd.fd, offset: fd.offset, length: fd.length };
    } finally {
      this.preparing = false;
    }
  }

  private async release(): Promise<void> {
    const p: media.AVPlayer | null = this.player;
    this.player = null;
    if (p === null) {
      return;
    }
    try {
      await p.release();
    } catch (_) {
      // 已经释放过了也会抛,无所谓
    }
  }

  dispose(): void {
    this.release();
  }
}
