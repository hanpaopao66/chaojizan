import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { OrderMessage } from '../model/Models';

/** 轮询间隔。订单内聊天是短时高频场景,3 秒够用也不至于太费 */
const POLL_MS: number = 3000;

/**
 * 订单内沟通。
 *
 * peer 是 rider 或 merchant。**两边分开**:同一句话对骑手和商家含义不同,
 * 混在一个会话里谁都不知道在跟谁说。
 *
 * 快捷短语是为了让用户在路上也能一键回 —— 打字很慢,而骑手在等。
 */
@Component
export struct ChatPage {
  orderNo: string = '';
  peer: string = 'rider';

  @State private messages: OrderMessage[] = [];
  @State private draft: string = '';
  @State private loading: boolean = true;
  @State private sending: boolean = false;

  private api: UserApi = new UserApi();
  private timer: number = -1;

  private static readonly QUICK: string[] = [
    '放门口就行,谢谢',
    '到了给我打电话',
    '不要辣,谢谢',
    '大概还要多久?',
  ];

  async aboutToAppear(): Promise<void> {
    await this.load();
    this.timer = setInterval(() => { this.load(); }, POLL_MS);
  }

  aboutToDisappear(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  private async load(): Promise<void> {
    try {
      const data: Record<string, Object> =
        await this.api.orderMessages(this.orderNo, this.peer);
      this.messages = (data['messages'] ?? []) as OrderMessage[];
    } catch (e) {
      // 轮询失败不打扰:下一轮会再试
    } finally {
      this.loading = false;
    }
  }

  private async send(text: string): Promise<void> {
    const content: string = text.trim();
    if (content.length === 0 || this.sending) {
      return;
    }
    this.sending = true;
    try {
      await this.api.sendOrderMessage(this.orderNo, this.peer, content);
      this.draft = '';
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.sending = false;
    }
  }

  @Builder
  private bubble(m: OrderMessage) {
    // 自己发的靠右。from_role 是 customer 就是我
    Row() {
      if (m.from_role === 'customer') {
        Blank();
      }
      Text(m.content)
        .fontSize(14)
        .fontColor(m.from_role === 'customer'
          ? $r('app.color.surface') : $r('app.color.ink'))
        .padding(10)
        .borderRadius(10)
        .backgroundColor(m.from_role === 'customer'
          ? $r('app.color.brand') : $r('app.color.surface'))
        .constraintSize({ maxWidth: '72%' });
      if (m.from_role !== 'customer') {
        Blank();
      }
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 4, bottom: 4 });
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.messages.length === 0) {
        Column() {
          Text(this.peer === 'rider' ? '还没有和骑手说过话' : '还没有和商家说过话')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 2 }) {
          ForEach(this.messages, (m: OrderMessage) => {
            ListItem() { this.bubble(m); }
          }, (m: OrderMessage) => `${m.id}`);
        }
        .width('100%').layoutWeight(1).scrollBar(BarState.Off);
      }

      // 快捷短语:用户多半在路上或在忙,打字很慢而对面在等
      Scroll() {
        Row({ space: 8 }) {
          ForEach(ChatPage.QUICK, (q: string) => {
            Text(q)
              .fontSize(12).fontColor($r('app.color.ink'))
              .padding({ left: 10, right: 10, top: 6, bottom: 6 })
              .borderRadius(12).backgroundColor($r('app.color.surface_alt'))
              .onClick(() => { this.send(q); });
          }, (q: string) => q);
        }
        .padding({ left: 12, right: 12, top: 6, bottom: 6 });
      }
      .scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off)
      .width('100%');

      Row({ space: 8 }) {
        TextInput({ placeholder: '说点什么', text: this.draft })
          .height(42).layoutWeight(1)
          .onChange((v: string) => { this.draft = v; })
          .onSubmit(() => { this.send(this.draft); });
        Button('发送')
          .height(42).width(70).fontSize(14)
          .enabled(!this.sending && this.draft.trim().length > 0)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.send(this.draft); });
      }
      .width('100%').padding(10).backgroundColor($r('app.color.surface'));
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
