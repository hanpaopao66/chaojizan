import { pasteboard } from '@kit.BasicServicesKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';

/**
 * 邀请好友。
 *
 * ⚠️ 说清楚**奖励是谁出的**:被邀请人完成首单后,由那家店的券批次
 * 给双方各发一张**本店券** —— 商家出钱,不是平台补贴。
 * 这个平台没有补贴预算,把它写成"平台送你券"就是撒谎。
 *
 * 商家没建券批次时只记关系不发券,这一条也要说,不然用户会以为被坑了。
 */
@Component
export struct InvitePage {
  @State private info: Record<string, Object> | null = null;
  @State private inputCode: string = '';
  @State private loading: boolean = true;
  @State private claiming: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    try {
      this.info = await this.api.myReferral();
    } catch (e) {
      this.info = null;
    } finally {
      this.loading = false;
    }
  }

  private str(key: string): string {
    if (this.info === null) {
      return '';
    }
    const v: Object = this.info[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private num(key: string): number {
    if (this.info === null) {
      return 0;
    }
    const v: Object = this.info[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  /**
   * 复制邀请话术。
   *
   * 安卓端的分享只有一句下载链接、**不带邀请码**,朋友装完还得手输六位数 ——
   * 转化全漏在那一步。这里把码直接写进话术里,至少省掉"你的码是多少"这一问。
   */
  private copyInvite(): void {
    const code: string = this.str('code');
    const text: string = `我在用超级赞点外卖 —— 商家只被抽 5%,` +
      `配送费一分不截留全归骑手,每一单的钱怎么分都能查。\n` +
      `下载 chaojizan.cc/download,注册时填我的邀请码 ${code}。`;
    const data: pasteboard.PasteData =
      pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, text);
    pasteboard.getSystemPasteboard().setData(data).then(() => {
      promptAction.showToast({ message: '已复制,粘给朋友就行', duration: 3000 });
    }).catch(() => {
      promptAction.showToast({ message: `你的邀请码 ${code}` });
    });
  }

  private async claim(): Promise<void> {
    const c: string = this.inputCode.trim();
    if (c.length === 0 || this.claiming) {
      return;
    }
    this.claiming = true;
    try {
      await this.api.claimReferral(c);
      promptAction.showToast({ message: '已填写,完成首单后双方各得一张商家券' });
      this.inputCode = '';
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.claiming = false;
    }
  }

  build() {
    Scroll() {
      Column({ space: 12 }) {
        if (this.loading) {
          Row() { LoadingProgress().width(24).height(24); }.width('100%');
        } else {
          Column({ space: 8 }) {
            Text('我的邀请码')
              .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
            Text(this.str('code'))
              .fontSize(30).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.brand')).width('100%');
            Text(`已邀请 ${this.num('invited_count')} 人`)
              .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
            Button('复制邀请话术')
              .height(40).fontSize(13)
              .backgroundColor($r('app.color.brand'))
              .onClick(() => { this.copyInvite(); });
          }
          .width('100%').padding(16).backgroundColor($r('app.color.surface'))
          .borderRadius(14).alignItems(HorizontalAlign.Start);
        }

        Column({ space: 6 }) {
          Text('奖励是商家出的,不是平台补贴')
            .fontSize(14).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Text('· 朋友完成首单后,由那家店给你们双方各发一张**本店券**')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
          Text('· 商家没建券批次时只记邀请关系、不发券 —— 这不是坑你,' +
            '是那家店没准备券')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
          Text('· 平台没有补贴预算,不做烧钱拉新。我们能给的是低抽成和透明账目')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);

        Column({ space: 8 }) {
          Text('填别人的邀请码')
            .fontSize(14).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Text('注册后 24 小时内可填')
            .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
          Row({ space: 10 }) {
            TextInput({ placeholder: '6 位邀请码', text: this.inputCode })
              .height(44).layoutWeight(1).maxLength(6)
              .onChange((v: string) => { this.inputCode = v; });
            Button(this.claiming ? '提交中…' : '填写')
              .height(44).width(80).fontSize(13)
              .enabled(!this.claiming && this.inputCode.trim().length > 0)
              .backgroundColor($r('app.color.brand'))
              .onClick(() => { this.claim(); });
          }
          .width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);
      }
      .width('100%').padding(12).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/**
 * 实名认证。
 *
 * 只有一个用途:**酒类订单要核验年龄**。不是拿来做用户画像的,
 * 所以这一页要把用途说死,并且说清楚身份证号存在哪。
 *
 * **客户端不缓存身份证号** —— 提交完就不再持有,不写偏好、不留状态。
 */
@Component
export struct IdentityPage {
  @State private status: Record<string, Object> | null = null;
  @State private realName: string = '';
  @State private idNo: string = '';
  @State private loading: boolean = true;
  @State private submitting: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    try {
      this.status = await this.api.identityStatus();
    } catch (e) {
      this.status = null;
    } finally {
      this.loading = false;
    }
  }

  private get verified(): boolean {
    if (this.status === null) {
      return false;
    }
    return this.status['verified'] === true;
  }

  private tail(): string {
    if (this.status === null) {
      return '';
    }
    const v: Object = this.status['id_tail'] ?? '';
    return typeof v === 'string' ? v : '';
  }

  /** 身份证校验位真算(GB 11643-1999),别只判 18 位 */
  private idValid(): boolean {
    const s: string = this.idNo.trim().toUpperCase();
    if (!/^\d{17}[\dX]$/.test(s)) {
      return false;
    }
    const w: number[] = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
    const map: string[] = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2'];
    let sum: number = 0;
    for (let i = 0; i < 17; i++) {
      sum += parseInt(s.charAt(i), 10) * w[i];
    }
    return map[sum % 11] === s.charAt(17);
  }

  private async submit(): Promise<void> {
    if (this.realName.trim().length === 0) {
      promptAction.showToast({ message: '请填真实姓名' });
      return;
    }
    if (!this.idValid()) {
      promptAction.showToast({ message: '身份证号校验位不对,核对一下' });
      return;
    }
    this.submitting = true;
    try {
      this.status = await this.api.verifyIdentity(
        this.realName.trim(), this.idNo.trim().toUpperCase());
      // 提交完立刻清掉,客户端不留身份证号
      this.idNo = '';
      promptAction.showToast({ message: '已提交' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.submitting = false;
    }
  }

  build() {
    Scroll() {
      Column({ space: 12 }) {
        Column({ space: 6 }) {
          Text('为什么要实名')
            .fontSize(15).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Text('只有一个用途:**买酒时核验年龄**。法律要求平台核实,' +
            '不核实就不能卖。')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text('不做用户画像、不用于推荐、不共享给商家和骑手。' +
            '身份证号在服务端加密存放,平台常规界面只看得到后 4 位。')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);

        if (this.loading) {
          Row() { LoadingProgress().width(24).height(24); }.width('100%');
        } else if (this.verified) {
          Column({ space: 4 }) {
            Text('已实名')
              .fontSize(16).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.earn')).width('100%');
            if (this.tail().length > 0) {
              Text(`证件尾号 ${this.tail()}`)
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
            }
          }
          .width('100%').padding(16).backgroundColor($r('app.color.surface'))
          .borderRadius(14).alignItems(HorizontalAlign.Start);
        } else {
          Column({ space: 10 }) {
            TextInput({ placeholder: '真实姓名', text: this.realName })
              .height(46).onChange((v: string) => { this.realName = v; });
            TextInput({ placeholder: '身份证号', text: this.idNo })
              .height(46).maxLength(18)
              .onChange((v: string) => { this.idNo = v; });
            Button(this.submitting ? '提交中…' : '提交认证')
              .width('100%').height(46)
              .enabled(!this.submitting)
              .backgroundColor($r('app.color.brand'))
              .onClick(() => { this.submit(); });
          }
          .width('100%').padding(16).backgroundColor($r('app.color.surface'))
          .borderRadius(14).alignItems(HorizontalAlign.Start);
        }
      }
      .width('100%').padding(12).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
