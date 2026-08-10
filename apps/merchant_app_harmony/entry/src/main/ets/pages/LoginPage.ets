import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { LoginResult, SmsCodeResult } from '../model/Models';

/**
 * 商家登录。
 *
 * 与用户端的差别只有一句文案:商家端**没有游客模式** ——
 * 不登录进来一件事也做不了,所以别写「不登录也能浏览」那种话。
 *
 * 服务端已经有 60 秒冷却、同号日 8 条、同 IP 日 20 条、第 3 条起滑块的防刷,
 * **客户端不要再自己造一套限制** —— 两套规则迟早对不上,表现成
 * 「按钮还能点但一点就报错」。客户端只做倒计时(防止重复点),
 * 服务端的报错原样显示。
 */
@Component
export struct LoginPage {
  onLoggedIn: () => void = () => {};

  @State private phone: string = '';
  @State private code: string = '';
  @State private sending: boolean = false;
  @State private submitting: boolean = false;
  @State private countdown: number = 0;
  @State private agreed: boolean = false;

  private api: MerchantApi = new MerchantApi();
  private timer: number = -1;

  aboutToDisappear(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  private get phoneOk(): boolean {
    return /^1[3-9]\d{9}$/.test(this.phone);
  }

  private startCountdown(): void {
    this.countdown = 60;
    if (this.timer >= 0) {
      clearInterval(this.timer);
    }
    this.timer = setInterval(() => {
      this.countdown -= 1;
      if (this.countdown <= 0) {
        clearInterval(this.timer);
        this.timer = -1;
      }
    }, 1000);
  }

  private async sendCode(): Promise<void> {
    if (!this.phoneOk || this.sending || this.countdown > 0) {
      return;
    }
    this.sending = true;
    try {
      const r: SmsCodeResult = await this.api.sendSmsCode(this.phone);
      this.startCountdown();
      if (r.dev_code !== undefined && r.dev_code.length > 0) {
        // 短信服务没配时服务端会把验证码直接回来(开发模式)。
        // 直接填进去省得手抄,但**要说明这是开发模式**,
        // 免得上线后有人以为验证码就该显示出来
        this.code = r.dev_code;
        promptAction.showToast({ message: `开发模式验证码:${r.dev_code}` });
      } else {
        promptAction.showToast({ message: '验证码已发送' });
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.sending = false;
    }
  }

  private async submit(): Promise<void> {
    if (!this.agreed) {
      promptAction.showToast({ message: '请先阅读并同意服务协议与隐私政策' });
      return;
    }
    if (!this.phoneOk || this.code.length < 4 || this.submitting) {
      return;
    }
    this.submitting = true;
    try {
      const r: LoginResult = await this.api.loginBySms(this.phone, this.code);
      await Session.get().saveLogin(r.token, r.user_id, r.name, this.phone);
      this.onLoggedIn();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.submitting = false;
    }
  }

  build() {
    Column({ space: 14 }) {
      Text('商家登录')
        .fontSize(24)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'))
        .width('100%')
        .margin({ top: 40, bottom: 4 });
      Text('用开店时登记的手机号登录')
        .fontSize(13)
        .fontColor($r('app.color.ink_muted'))
        .width('100%');

      TextInput({ placeholder: '手机号', text: this.phone })
        .type(InputType.PhoneNumber)
        .maxLength(11)
        .height(48)
        .onChange((v: string) => { this.phone = v; });

      Row({ space: 10 }) {
        TextInput({ placeholder: '验证码', text: this.code })
          .type(InputType.Number)
          .maxLength(6)
          .height(48)
          .layoutWeight(1)
          .onChange((v: string) => { this.code = v; });
        Button(this.countdown > 0 ? `${this.countdown}s` : '获取验证码')
          .height(48)
          .width(112)
          .fontSize(14)
          .enabled(this.phoneOk && this.countdown === 0 && !this.sending)
          .backgroundColor(this.phoneOk && this.countdown === 0
            ? $r('app.color.brand') : $r('app.color.line'))
          .onClick(() => { this.sendCode(); });
      }
      .width('100%');

      Row({ space: 8 }) {
        Checkbox()
          .select(this.agreed)
          .selectedColor($r('app.color.brand'))
          .onChange((v: boolean) => { this.agreed = v; });
        Text('我已阅读并同意《商家服务协议》与《隐私政策》')
          .fontSize(12)
          .fontColor($r('app.color.ink_muted'))
          .layoutWeight(1);
      }
      .width('100%')
      .margin({ top: 4 });

      Button(this.submitting ? '登录中…' : '登录')
        .width('100%')
        .height(48)
        .enabled(this.phoneOk && this.code.length >= 4 && !this.submitting)
        .backgroundColor($r('app.color.brand'))
        .onClick(() => { this.submit(); });

      // 佣金写在登录页上。商家在这一屏最想知道的就是"你抽我多少"
      Text('佣金只抽 5%,单量越大费率越低 · 每笔账都可查')
        .fontSize(12)
        .fontColor($r('app.color.earn'))
        .width('100%')
        .margin({ top: 2 });
    }
    .width('100%')
    .height('100%')
    .padding({ left: 22, right: 22 })
    .backgroundColor($r('app.color.surface'))
    .alignItems(HorizontalAlign.Start);
  }
}
