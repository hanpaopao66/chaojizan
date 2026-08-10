import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { ArrayDataSource } from '../common/DataSource';

/**
 * 消息中心。
 *
 * 收拢两类内容:平台公告(置顶)+ 触达记录(评价/系统,按分类筛选)。
 * **订单类消息不进这里** —— 订单页本身就是它们的家,再堆一份只会淹掉
 * 真正需要看的。
 *
 * 进入即记已读水位,店铺页的未读角标随之清零。
 *
 * ## 「这一栏没有消息」和「没拉到」不能长得一样
 *
 * 差评通知看不到,商家就错过了申诉窗口 —— 而判责一旦生效,
 * 钱是从结算款里扣的。
 */
@Component
export struct MessagesPage {
  onBack: () => void = () => {};

  /** null 全部 / review / system */
  @State private category: string = '';
  @State private announcements: Record<string, Object>[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private loadingMore: boolean = false;

  private api: MerchantApi = new MerchantApi();
  private ds: ArrayDataSource<Record<string, Object>> =
      new ArrayDataSource<Record<string, Object>>();
  private hasMore: boolean = true;
  private pageSize: number = 50;

  aboutToAppear(): void {
    this.reload();
    // 进来就算看过:水位记到现在,角标清零。失败静默 ——
    // 角标没清是小事,为它弹个错误反而打扰
    this.api.merchantMessagesRead().catch(() => {});
  }

  private async reload(): Promise<void> {
    const at: string = this.category;
    try {
      const data: Record<string, Object> = await this.api.merchantMessages(
          this.category.length === 0 ? undefined : this.category);
      if (this.category !== at) {
        return; // 弱网下快速切分类:先发后至的旧响应不能覆盖新分类
      }
      const ann: Object | undefined = data['announcements'];
      this.announcements =
          (ann === undefined ? [] : ann) as Record<string, Object>[];
      const msgs: Object | undefined = data['messages'];
      const list: Record<string, Object>[] =
          (msgs === undefined ? [] : msgs) as Record<string, Object>[];
      this.ds.reload(list);
      // 页大小以服务端为准:写死的阈值一旦和服务端不一致,
      // 就会在"刚好不满一页"时误判成没有下一页
      const ps: Object | undefined = data['page_size'];
      this.pageSize = ps === undefined ? 50 : ps as number;
      this.hasMore = list.length >= this.pageSize;
      this.errorText = '';
    } catch (e) {
      if (this.category === at) {
        this.errorText = (e as ApiException).message;
      }
    } finally {
      this.loaded = true;
    }
  }

  private async loadMore(): Promise<void> {
    if (this.loadingMore || !this.hasMore) {
      return;
    }
    const all: Record<string, Object>[] = this.ds.all;
    if (all.length === 0) {
      return;
    }
    this.loadingMore = true;
    const at: string = this.category;
    try {
      const data: Record<string, Object> = await this.api.merchantMessages(
          this.category.length === 0 ? undefined : this.category,
          all[all.length - 1]['id'] as number);
      if (this.category !== at) {
        return;
      }
      const msgs: Object | undefined = data['messages'];
      const more: Record<string, Object>[] =
          (msgs === undefined ? [] : msgs) as Record<string, Object>[];
      this.ds.append(more);
      this.hasMore = more.length > 0;
    } catch (_) {
      // 上拉失败不打扰,下次滚动再试
    } finally {
      this.loadingMore = false;
    }
  }

  private dateLabel(iso: string): string {
    const t: Date = new Date(iso);
    if (isNaN(t.getTime())) {
      return '';
    }
    const two = (n: number): string => n < 10 ? `0${n}` : `${n}`;
    return `${t.getMonth() + 1}-${t.getDate()} ` +
        `${two(t.getHours())}:${two(t.getMinutes())}`;
  }

  @Builder
  private messageRow(m: Record<string, Object>) {
    Row({ space: 10 }) {
      Text(m['kind'] === 'review' ? '💬' : '🔔').fontSize(16);
      Column({ space: 3 }) {
        Text(`${m['title'] ?? ''}`)
          .fontSize(14).fontColor($r('app.color.ink')).width('100%');
        Text(`${m['content'] ?? ''}`)
          .fontSize(12).lineHeight(18)
          .fontColor($r('app.color.ink_muted'))
          .maxLines(2).textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%');
      }
      .alignItems(HorizontalAlign.Start).layoutWeight(1);
      Text(this.dateLabel(`${m['created_at'] ?? ''}`))
        .fontSize(11).fontColor($r('app.color.ink_muted'));
    }
    .width('100%').padding(12)
    .backgroundColor($r('app.color.surface')).borderRadius(10)
    .margin({ bottom: 8 });
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('消息中心')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Row({ space: 8 }) {
        ForEach(['', 'review', 'system'], (c: string) => {
          Text(c.length === 0 ? '全部' : c === 'review' ? '评价' : '系统')
            .fontSize(12)
            .fontColor(this.category === c ? Color.White : $r('app.color.ink'))
            .padding({ left: 12, right: 12, top: 5, bottom: 5 })
            .borderRadius(12)
            .backgroundColor(this.category === c
              ? $r('app.color.brand') : $r('app.color.surface_alt'))
            .onClick(() => {
              this.category = c;
              this.loaded = false;
              this.hasMore = true;
              this.reload();
            });
        }, (c: string) => `c${c}`);
      }
      .width('100%').padding({ left: 12, right: 12, top: 8, bottom: 4 });

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.errorText.length > 0) {
        // 差评通知看不到就错过申诉窗口。「没有消息」和「没拉到」必须分开
        Column({ space: 12 }) {
          Text('消息没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText).fontSize(13)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.reload(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Column() {
          ForEach(this.announcements, (a: Record<string, Object>) => {
            Column({ space: 4 }) {
              Row({ space: 6 }) {
                Text('📢').fontSize(14);
                Text(`${a['title'] ?? ''}`)
                  .fontSize(14).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).layoutWeight(1);
                Text(this.dateLabel(`${a['created_at'] ?? ''}`))
                  .fontSize(11).fontColor($r('app.color.ink_muted'));
              }
              .width('100%');
              Text(`${a['content'] ?? ''}`)
                .fontSize(12).lineHeight(18)
                .fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(12)
            .backgroundColor($r('app.color.surface_alt')).borderRadius(10)
            .margin({ bottom: 8 });
          }, (a: Record<string, Object>) => `a${a['id']}`);

          if (this.ds.totalCount() === 0) {
            Text('这一栏没有消息')
              .fontSize(14).fontColor($r('app.color.ink_muted'))
              .width('100%').textAlign(TextAlign.Center)
              .padding({ top: 40, bottom: 40 });
          } else {
            // 通知是翻页加载的,越滚越长 —— 必须按需构建
            List() {
              LazyForEach(this.ds, (m: Record<string, Object>) => {
                ListItem() {
                  this.messageRow(m);
                }
              }, (m: Record<string, Object>) => `${m['id']}`);
            }
            .layoutWeight(1).width('100%').scrollBar(BarState.Off)
            .onReachEnd(() => { this.loadMore(); });
          }
        }
        .layoutWeight(1).width('100%')
        .padding({ left: 12, right: 12, top: 6 });
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
