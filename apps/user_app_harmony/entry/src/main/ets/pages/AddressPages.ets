import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { geoLocationManager } from '@kit.LocationKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi, AddressIn } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Address, ParsedAddress } from '../model/Models';

/**
 * 地址簿。
 *
 * 楼层和电梯这两个字段**要收**:服务端按它算上门难度费(全额归骑手),
 * 也让 ETA 诚实一点 —— 爬 6 楼确实更慢。收的时候把原因说出来,
 * 不解释就问楼层,用户会以为平台在打听什么。
 */
@Component
export struct AddressListPage {
  /** 选择模式:从结算页进来时选中即返回 */
  selectMode: boolean = false;
  onPick: (addr: Address) => void = () => {};
  onEdit: (addr: Address | null) => void = () => {};

  @State private list: Address[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  async onPageShow(): Promise<void> {
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      this.list = await this.api.addresses();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private async remove(a: Address): Promise<void> {
    try {
      await this.api.deleteAddress(a.id);
      await this.load();
      promptAction.showToast({ message: '已删除' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  @Builder
  private card(a: Address) {
    Column({ space: 4 }) {
      Row({ space: 6 }) {
        Text(a.address)
          .fontSize(15).fontColor($r('app.color.ink')).layoutWeight(1)
          .maxLines(2).textOverflow({ overflow: TextOverflow.Ellipsis });
        if (a.is_default === true) {
          Text('默认').fontSize(11).fontColor($r('app.color.brand'));
        }
      }
      .width('100%');
      if ((a.detail ?? '').length > 0) {
        Text(a.detail)
          .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      }
      Text(`${a.contact_name} ${a.contact_phone}`)
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      if (a.floor !== undefined && a.floor !== null) {
        Text(a.has_elevator === true
          ? `${a.floor} 楼 · 有电梯` : `${a.floor} 楼 · 无电梯`)
          .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
      }
      Row({ space: 16 }) {
        Text('编辑').fontSize(12).fontColor($r('app.color.ink_muted'))
          .onClick(() => { this.onEdit(a); });
        Text('删除').fontSize(12).fontColor($r('app.color.ink_muted'))
          .onClick(() => { this.remove(a); });
      }
      .width('100%').margin({ top: 4 });
    }
    .width('100%').padding(14)
    .backgroundColor($r('app.color.surface')).borderRadius(14)
    .alignItems(HorizontalAlign.Start)
    .onClick(() => {
      if (this.selectMode) {
        this.onPick(a);
      }
    });
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.list.length === 0) {
        Column({ space: 10 }) {
          Text('还没有收货地址')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('添加地址')
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.onEdit(null); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.list, (a: Address) => {
            ListItem() { this.card(a); }
          }, (a: Address) => `${a.id}`);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12 })
        .scrollBar(BarState.Off);

        Button('添加地址')
          .width('92%').height(46).margin({ bottom: 14 })
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.onEdit(null); });
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}

/**
 * 新增 / 编辑地址。
 *
 * **智能识别**是这一页最省事的功能:粘贴一段
 * 「张三 13800138000 成都市锦江区春熙路 21 号 3 栋 502」自动拆字段。
 * 但拆完一定要让用户能改 —— 识别是省事,不是代替用户确认。
 */
@Component
export struct AddressEditPage {
  editing: Address | null = null;
  onSaved: () => void = () => {};

  @State private contactName: string = '';
  @State private contactPhone: string = '';
  @State private address: string = '';
  @State private detail: string = '';
  @State private floorText: string = '';
  @State private hasElevator: boolean = true;
  @State private isDefault: boolean = false;
  @State private paste: string = '';
  @State private lat: number = 0;
  @State private lng: number = 0;
  @State private located: boolean = false;
  @State private saving: boolean = false;
  /** 地址搜索联想。不依赖地图 SDK,服务端代理的 */
  @State private tips: Record<string, Object>[] = [];
  @State private searching: boolean = false;

  private api: UserApi = new UserApi();
  private tipTimer: number = -1;

  private tipStr(t: Record<string, Object>, key: string): string {
    const v: Object = t[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private tipNum(t: Record<string, Object>, key: string): number {
    const v: Object = t[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  /** 输入时联想。250ms 防抖 —— 每敲一个字发一次既费流量也打服务端 */
  private onAddressInput(v: string): void {
    this.address = v;
    if (this.tipTimer >= 0) {
      clearTimeout(this.tipTimer);
    }
    if (v.trim().length < 2) {
      this.tips = [];
      return;
    }
    this.tipTimer = setTimeout(() => {
      this.searching = true;
      this.api.geoTips(v.trim(), '')
        .then((list: Record<string, Object>[]) => { this.tips = list; })
        .catch(() => { this.tips = []; })
        .finally(() => { this.searching = false; });
      this.tipTimer = -1;
    }, 250);
  }

  /** 选中一条联想:地址和坐标一起带过来,省掉"用当前位置"那一步 */
  private pickTip(t: Record<string, Object>): void {
    this.address = this.tipStr(t, 'name');
    const lat: number = this.tipNum(t, 'lat');
    const lng: number = this.tipNum(t, 'lng');
    if (lat !== 0 && lng !== 0) {
      this.lat = lat;
      this.lng = lng;
      this.located = true;
    }
    this.tips = [];
  }

  aboutToAppear(): void {
    const a: Address | null = this.editing;
    if (a !== null) {
      this.contactName = a.contact_name;
      this.contactPhone = a.contact_phone;
      this.address = a.address;
      this.detail = a.detail ?? '';
      this.floorText = a.floor !== undefined && a.floor !== null
        ? `${a.floor}` : '';
      this.hasElevator = a.has_elevator !== false;
      this.isDefault = a.is_default === true;
      this.lat = a.lat;
      this.lng = a.lng;
      this.located = true;
    }
  }

  /** 用当前定位作为坐标。没有地图选点时这是唯一能拿到经纬度的路 */
  private async useCurrentLocation(): Promise<void> {
    try {
      const context = getContext(this) as common.UIAbilityContext;
      const permissions: Permissions[] = ['ohos.permission.APPROXIMATELY_LOCATION'];
      const atManager = abilityAccessCtrl.createAtManager();
      const granted = await atManager.requestPermissionsFromUser(context, permissions);
      if (granted.authResults.length === 0 || granted.authResults[0] !== 0) {
        promptAction.showToast({ message: '没有定位权限,可以手动填地址' });
        return;
      }
      const request: geoLocationManager.CurrentLocationRequest = {
        priority: geoLocationManager.LocationRequestPriority.ACCURACY,
        scenario: geoLocationManager.LocationRequestScenario.UNSET,
        timeoutMs: 8000,
      };
      const loc = await geoLocationManager.getCurrentLocation(request);
      this.lat = loc.latitude;
      this.lng = loc.longitude;
      this.located = true;
      // 逆地理:把坐标变成一句人话填进去,用户不用自己打
      try {
        const poi: Record<string, Object> =
          await this.api.geoReverse(this.lat, this.lng);
        const name: string = this.tipStr(poi, 'name');
        if (name.length > 0 && this.address.trim().length === 0) {
          this.address = name;
        }
      } catch (e) {
        // 逆地理失败不影响:坐标已经拿到了
      }
      promptAction.showToast({ message: '已用当前位置定位' });
    } catch (e) {
      promptAction.showToast({ message: '定位失败,可以手动填地址' });
    }
  }

  private async smartParse(): Promise<void> {
    const text: string = this.paste.trim();
    if (text.length === 0) {
      return;
    }
    try {
      const p: ParsedAddress = await this.api.parseAddress(text);
      // 只覆盖识别出来的字段,识别不出的保留用户已填的
      if ((p.contact_name ?? '').length > 0) {
        this.contactName = p.contact_name as string;
      }
      if ((p.contact_phone ?? '').length > 0) {
        this.contactPhone = p.contact_phone as string;
      }
      if ((p.address ?? '').length > 0) {
        this.address = p.address as string;
      }
      if ((p.detail ?? '').length > 0) {
        this.detail = p.detail as string;
      }
      promptAction.showToast({ message: '已识别,请核对一下' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private get valid(): boolean {
    return this.contactName.trim().length > 0
      && /^1[3-9]\d{9}$/.test(this.contactPhone)
      && this.address.trim().length > 0
      && this.located;
  }

  private async save(): Promise<void> {
    if (!this.valid || this.saving) {
      if (!this.located) {
        promptAction.showToast({ message: '请先点「用当前位置」拿到坐标' });
      }
      return;
    }
    this.saving = true;
    try {
      const floor: number = parseInt(this.floorText, 10);
      const body: AddressIn = {
        contact_name: this.contactName.trim(),
        contact_phone: this.contactPhone.trim(),
        address: this.address.trim(),
        detail: this.detail.trim(),
        lat: this.lat,
        lng: this.lng,
        is_default: this.isDefault,
        floor: isNaN(floor) ? undefined : floor,
        has_elevator: isNaN(floor) ? undefined : this.hasElevator,
      };
      if (this.editing !== null) {
        await this.api.updateAddress(this.editing.id, body);
      } else {
        await this.api.addAddress(body);
      }
      promptAction.showToast({ message: '已保存' });
      this.onSaved();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.saving = false;
    }
  }

  build() {
    Scroll() {
      Column({ space: 12 }) {
        Column({ space: 6 }) {
          Text('粘贴一段地址,自动拆字段')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          TextArea({
            placeholder: '例:张三 13800138000 成都市锦江区春熙路21号3栋502',
            text: this.paste,
          })
            .height(72)
            .onChange((v: string) => { this.paste = v; });
          Button('识别')
            .height(36).fontSize(13)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.smartParse(); });
        }
        .width('100%').padding(14).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        TextInput({ placeholder: '收货人', text: this.contactName })
          .height(46).onChange((v: string) => { this.contactName = v; });
        TextInput({ placeholder: '手机号', text: this.contactPhone })
          .type(InputType.PhoneNumber).maxLength(11).height(46)
          .onChange((v: string) => { this.contactPhone = v; });
        TextInput({ placeholder: '搜小区/写字楼/学校', text: this.address })
          .height(46).onChange((v: string) => { this.onAddressInput(v); });
        if (this.tips.length > 0) {
          Column() {
            ForEach(this.tips.slice(0, 6), (t: Record<string, Object>) => {
              Column({ space: 2 }) {
                Text(this.tipStr(t, 'name'))
                  .fontSize(14).fontColor($r('app.color.ink')).width('100%');
                if (this.tipStr(t, 'address').length > 0) {
                  Text(this.tipStr(t, 'address'))
                    .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
                }
              }
              .width('100%').padding(10)
              .alignItems(HorizontalAlign.Start)
              .onClick(() => { this.pickTip(t); });
            }, (t: Record<string, Object>) => this.tipStr(t, 'name'));
          }
          .width('100%').backgroundColor($r('app.color.surface'))
          .borderRadius(10);
        }
        TextInput({ placeholder: '门牌号(如 3栋502)', text: this.detail })
          .height(46).onChange((v: string) => { this.detail = v; });

        Row({ space: 10 }) {
          TextInput({ placeholder: '楼层(选填)', text: this.floorText })
            .type(InputType.Number).height(46).layoutWeight(1)
            .onChange((v: string) => { this.floorText = v; });
          Text('有电梯').fontSize(13).fontColor($r('app.color.ink_muted'));
          Toggle({ type: ToggleType.Switch, isOn: this.hasElevator })
            .onChange((on: boolean) => { this.hasElevator = on; });
        }
        .width('100%');

        // 为什么问楼层要说清楚 —— 不解释就问,用户会以为平台在打听什么
        Text('填了楼层,骑手接单前就知道要不要爬楼;无电梯高楼层会有上门难度费,' +
          '这笔钱全额归骑手,你也可以选择送到楼下不付它。')
          .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');

        Row() {
          Text(this.located ? `已定位 (${this.lat.toFixed(4)}, ${this.lng.toFixed(4)})`
            : '还没有坐标')
            .fontSize(12)
            .fontColor(this.located
              ? $r('app.color.earn') : $r('app.color.brand'))
            .layoutWeight(1);
          Button('用当前位置')
            .height(34).fontSize(12)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.useCurrentLocation(); });
        }
        .width('100%');

        Row() {
          Text('设为默认地址')
            .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
          Toggle({ type: ToggleType.Switch, isOn: this.isDefault })
            .onChange((on: boolean) => { this.isDefault = on; });
        }
        .width('100%');

        Button(this.saving ? '保存中…' : '保存')
          .width('100%').height(46)
          .enabled(this.valid && !this.saving)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.save(); });
      }
      .width('100%').padding(16).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
