import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';
const STORE: string = 'superz_session';

const K_TOKEN: string = 'auth_token';
const K_USER_ID: string = 'auth_user_id';
const K_USER_NAME: string = 'auth_user_name';
const K_USER_PHONE: string = 'auth_user_phone';
const K_PRIVACY: string = 'privacy_agreed_version';
const K_ELDER: string = 'elder_mode';
const K_SHOP_ID: string = 'merchant_shop_id';

/**
 * 会话与本地偏好。
 *
 * **存 preferences 不存 AppStorage。** AppStorage 是内存态,杀进程就没了,
 * 而"冷启动免登录"是安卓端既有的行为 —— 外卖是高频低耐心的场景,
 * 每次打开都要重登会直接劝退。
 *
 * 隐私同意版本号也放这里:它是所有网络请求的前置闸门,
 * 必须在任何请求之前就能读到。
 */
export class Session {
  private static instance: Session | null = null;
  private store: preferences.Preferences | null = null;

  token: string = '';
  userId: number = 0;
  userName: string = '';
  userPhone: string = '';

  /**
   * 连锁商家上次选中的门店。
   *
   * **必须持久化**:每次冷启动都回到「请选择门店」,对一个每天开关几十次
   * 应用的商家是折磨;更糟的是他可能随手点错一家,然后对着别家店备餐。
   *
   * 单店商家这里一直是 null。
   */
  shopId: number | null = null;

  static get(): Session {
    if (Session.instance === null) {
      Session.instance = new Session();
    }
    return Session.instance;
  }

  get isLoggedIn(): boolean {
    return this.token.length > 0;
  }

  /** 冷启动时调一次。拿不到存储也不能崩 —— 大不了当没登录 */
  async init(context: common.UIAbilityContext): Promise<void> {
    try {
      this.store = await preferences.getPreferences(context, STORE);
      this.token = await this.readString(K_TOKEN);
      this.userId = await this.readNumber(K_USER_ID);
      this.userName = await this.readString(K_USER_NAME);
      this.userPhone = await this.readString(K_USER_PHONE);
      const sid: number = await this.readNumber(K_SHOP_ID);
      this.shopId = sid > 0 ? sid : null;
    } catch (e) {
      hilog.error(DOMAIN, TAG, '会话恢复失败,按未登录处理');
    }
  }

  async saveLogin(token: string, userId: number, name: string, phone: string): Promise<void> {
    this.token = token;
    this.userId = userId;
    this.userName = name;
    this.userPhone = phone;
    await this.writeString(K_TOKEN, token);
    await this.writeNumber(K_USER_ID, userId);
    await this.writeString(K_USER_NAME, name);
    await this.writeString(K_USER_PHONE, phone);
  }

  /** 记住当前门店。切店时和 Api.shopId 一起改,别只改一个 */
  async saveShopId(id: number | null): Promise<void> {
    this.shopId = id;
    await this.writeNumber(K_SHOP_ID, id === null ? 0 : id);
  }

  /**
   * 清会话。401 也走这里。
   * **手机号一起清掉** —— 留着的话下一个人登录时输入框里是上一个人的号,
   * 那是别人的个人信息
   */
  async clear(): Promise<void> {
    this.token = '';
    this.userId = 0;
    this.userName = '';
    this.userPhone = '';
    // 门店一起清:换个账号登录时留着上一个账号的门店 id,
    // 第一个请求就会带着别人的 X-Shop-Id 出去
    this.shopId = null;
    await this.writeNumber(K_SHOP_ID, 0);
    await this.writeString(K_TOKEN, '');
    await this.writeNumber(K_USER_ID, 0);
    await this.writeString(K_USER_NAME, '');
    await this.writeString(K_USER_PHONE, '');
  }

  /**
   * 长辈版(大字)。
   *
   * 外卖用户里老年人不少,这不是可选项。实现走**应用级字体缩放**
   * (`applicationContext.setFontSizeScale`),一处生效全局 ——
   * 比在每个 fontSize 上乘系数靠谱得多:后者一定会漏,
   * 而漏掉的那几处正好是最需要放大的小字。
   *
   * 1.4 是封顶值:再大布局会溢出。安卓端也是这个数。
   */
  async elderMode(): Promise<boolean> {
    if (this.store === null) {
      return false;
    }
    const v: preferences.ValueType = await this.store.get(K_ELDER, false);
    return v === true;
  }

  async setElderMode(on: boolean): Promise<void> {
    if (this.store === null) {
      return;
    }
    await this.store.put(K_ELDER, on);
    await this.store.flush();
  }

  /** 已同意的隐私政策版本;没同意过返回空串 */
  async agreedPrivacyVersion(): Promise<string> {
    return await this.readString(K_PRIVACY);
  }

  async agreePrivacy(version: string): Promise<void> {
    await this.writeString(K_PRIVACY, version);
  }

  private async readString(key: string): Promise<string> {
    if (this.store === null) {
      return '';
    }
    const v: preferences.ValueType = await this.store.get(key, '');
    return typeof v === 'string' ? v : '';
  }

  private async readNumber(key: string): Promise<number> {
    if (this.store === null) {
      return 0;
    }
    const v: preferences.ValueType = await this.store.get(key, 0);
    return typeof v === 'number' ? v : 0;
  }

  private async writeString(key: string, value: string): Promise<void> {
    if (this.store === null) {
      return;
    }
    await this.store.put(key, value);
    await this.store.flush();
  }

  private async writeNumber(key: string, value: number): Promise<void> {
    if (this.store === null) {
      return;
    }
    await this.store.put(key, value);
    await this.store.flush();
  }
}
