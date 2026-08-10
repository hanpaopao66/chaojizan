import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Session } from './Session';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/** 后端地址。编译期由 build-profile.json5 的 buildProfileFields 注入 */
const DEFAULT_BASE_URL: string = 'https://chaojizan.cc';

/** 业务异常。message 一律是能直接显示给用户的中文 */
export class ApiException extends Error {
  statusCode: number;

  constructor(statusCode: number, message: string) {
    super(message);
    this.statusCode = statusCode;
    this.name = 'ApiException';
  }
}

/**
 * 把底层网络异常翻成人话。
 *
 * 不翻的后果安卓端实测过:断网时界面上会出现一长串带内部接口地址、端口
 * 和查询参数的原始异常 —— 用户看不懂,而且截图发出去就是一次信息泄露。
 * **网络类异常一律不许原样冒到 UI。**
 *
 * 错误码对照见鸿蒙 Network Kit 文档;这里只挑用户真会遇到的几类。
 */
function asFriendly(error: BusinessError | Error): ApiException {
  if (error instanceof ApiException) {
    return error;
  }
  const code: number = (error as BusinessError).code ?? 0;
  const raw: string = error.message ?? '';
  // 2300028 超时 / 2300007 域名解析失败 / 2300006 主机不可达 / 2300035 SSL 握手
  if (code === 2300028) {
    return new ApiException(0, '连接超时,换个网络或稍后再试');
  }
  if (code === 2300006 || code === 2300007) {
    return new ApiException(0, '网络好像断了,检查一下网络再试');
  }
  if (code === 2300035 || code === 2300060) {
    return new ApiException(0, '安全连接建立失败,换个网络再试');
  }
  if (raw.indexOf('JSON') >= 0 || raw.indexOf('Unexpected token') >= 0) {
    // 服务端返回了非 JSON:多半是被网关/校园网劫持到了门户页
    return new ApiException(0, '返回内容异常,可能被网络劫持,换个网络再试');
  }
  hilog.warn(DOMAIN, TAG, '未归类的网络错误 code=%{public}d', code);
  return new ApiException(0, '出了点问题,请稍后再试');
}

/** 服务端错误体:FastAPI 的 {"detail": "..."} */
interface ErrorBody {
  detail?: string;
}

/**
 * 用户端唯一的网络出口。
 *
 * **任何页面都不许自己 `http.createHttp()`。** 安卓端做到了用户端零处裸调
 * (全部经 ApiClient),好处是超时、鉴权、401 处理、错误文案只有一份口径;
 * 一旦开了口子,就会出现"这个页面的报错是中文、那个页面是英文堆栈"。
 */
export class Api {
  private static instance: Api | null = null;
  baseUrl: string = DEFAULT_BASE_URL;

  /**
   * 连锁商家当前选中的门店,随每个请求以 `X-Shop-Id` 头带上。
   *
   * **这是商家端最容易出人命的一个字段。** 它决定了「我在操作哪家店」——
   * 切店时漏换,商家就会对着二店的界面改总店的菜、提总店的钱。
   * 所以它放在这一层(唯一的网络出口),而不是让每个页面自己拼参数。
   *
   * 单店商家是 null,服务端按账号直接定位。
   */
  shopId: number | null = null;

  /** 401 时的回调:由根页面挂上去,负责把用户送回登录页 */
  onUnauthorized: (() => void) | null = null;

  static get(): Api {
    if (Api.instance === null) {
      Api.instance = new Api();
    }
    return Api.instance;
  }

  /**
   * 发一个请求,返回解析后的 JSON。
   *
   * 调用方按自己的接口类型 `as` 过去。这里不做泛型强转是有意的:
   * ArkTS 的类型系统在运行时不校验 JSON 形状,假装类型安全反而会掩盖
   * 服务端字段变化 —— 不如让调用方显式写出它期待什么。
   */
  async request(method: string, path: string, body?: object,
                query?: Record<string, string>): Promise<object | null> {
    const text: string = await this.requestRaw(method, path, body, query);
    if (text.length === 0) {
      return null;
    }
    return JSON.parse(text) as object;
  }

  /**
   * 返回纯文本而不是 JSON 的接口。
   *
   * 目前只有对账单 CSV(`/merchants/me/statement.csv`)。**别拿它当
   * 通用出口** —— 走这条路的响应不会被 JSON 解析,服务端要是回了
   * 一段 HTML 错误页,调用方会把整页 HTML 当成数据。
   */
  async requestText(method: string, path: string,
                    query?: Record<string, string>): Promise<string> {
    return this.requestRaw(method, path, undefined, query);
  }

  private buildUrl(path: string, query?: Record<string, string>): string {
    let url: string = `${this.baseUrl}${path}`;
    if (query !== undefined) {
      const parts: string[] = [];
      const keys: string[] = Object.keys(query);
      for (let i = 0; i < keys.length; i++) {
        const k: string = keys[i];
        const v: string = query[k];
        parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
      }
      if (parts.length > 0) {
        url = `${url}?${parts.join('&')}`;
      }
    }
    return url;
  }

  private async requestRaw(method: string, path: string, body?: object,
                           query?: Record<string, string>): Promise<string> {
    const url: string = this.buildUrl(path, query);

    const session: Session = Session.get();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (session.token.length > 0) {
      headers['Authorization'] = `Bearer ${session.token}`;
    }
    // 连锁商家当前选中的门店。见 [shopId] 上那段说明
    if (this.shopId !== null) {
      headers['X-Shop-Id'] = `${this.shopId}`;
    }

    const httpRequest: http.HttpRequest = http.createHttp();
    try {
      const options: http.HttpRequestOptions = {
        method: this.toMethod(method),
        header: headers,
        extraData: body === undefined ? undefined : JSON.stringify(body),
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: 15000,
        readTimeout: 15000,
      };
      const resp: http.HttpResponse = await httpRequest.request(url, options);
      const text: string = typeof resp.result === 'string' ? resp.result : '';

      if (resp.responseCode >= 400) {
        let message: string = `请求失败(${resp.responseCode})`;
        try {
          const err: ErrorBody = JSON.parse(text) as ErrorBody;
          if (err.detail !== undefined && err.detail.length > 0) {
            message = err.detail;
          }
        } catch (_) {
          // 错误体不是 JSON 就用兜底文案,不要把 HTML 甩给用户
        }
        if (resp.responseCode === 401 && session.isLoggedIn
            && path.indexOf('/auth/') !== 0) {
          // 登录态失效:清会话,静默回登录页(不弹一屏报错)
          await session.clear();
          if (this.onUnauthorized !== null) {
            this.onUnauthorized();
          }
        }
        throw new ApiException(resp.responseCode, message);
      }

      return text;
    } catch (e) {
      throw asFriendly(e as BusinessError);
    } finally {
      httpRequest.destroy();
    }
  }

  private toMethod(method: string): http.RequestMethod {
    if (method === 'POST') {
      return http.RequestMethod.POST;
    }
    if (method === 'PUT') {
      return http.RequestMethod.PUT;
    }
    if (method === 'DELETE') {
      return http.RequestMethod.DELETE;
    }
    return http.RequestMethod.GET;
  }

  /**
   * 图片等静态资源的完整地址。
   * 服务端下发的可能是 `/uploads/x.jpg` 这样的相对路径
   */
  resolveUrl(url: string): string {
    if (url.length === 0) {
      return '';
    }
    if (url.indexOf('http://') === 0 || url.indexOf('https://') === 0) {
      return url;
    }
    return `${this.baseUrl}${url.indexOf('/') === 0 ? '' : '/'}${url}`;
  }
}
