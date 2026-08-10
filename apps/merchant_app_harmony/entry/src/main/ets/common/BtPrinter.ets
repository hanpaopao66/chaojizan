import { socket, connection, constant } from '@kit.ConnectivityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { orderTicket, testTicket } from './Escpos';
import { MerchantOrder } from '../model/Models';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/** 串口服务的标准 UUID。市面上的 ESC/POS 蓝牙小票机都认这个 */
const SPP_UUID: string = '00001101-0000-1000-8000-00805f9b34fb';

const STORE: string = 'bt_printer';
const K_ADDR: string = 'addr';
const K_NAME: string = 'name';
const K_AUTO: string = 'auto';

/** 没选过打印机。调用方据此决定是否走云打印兜底 */
export const NO_DEVICE: string = 'NO_DEVICE';

/** 一台已配对的设备 */
export interface PairedDevice {
  addr: string;
  name: string;
}

/**
 * 蓝牙小票机直连:通用 58mm ESC/POS 热敏打印机。
 *
 * 与云打印(服务端飞鹅直推)互为补充:蓝牙零成本复用商家现有设备,
 * 但依赖商家手机在场;云打印反之。两者都配置时会各出一张。
 *
 * ## 与安卓端的差别
 *
 * 排版层(Escpos.ets)是逐行搬过来的,**只有传输层是重写的**。
 * 鸿蒙用 `@kit.ConnectivityKit` 的 `socket.sppConnect` + `sppWrite`。
 *
 * ## 配对要去系统设置
 *
 * 鸿蒙侧应用内直接配对经典蓝牙的路子不通畅。界面上必须直说
 * 「先去系统设置里和打印机配对,再回来选」—— 否则商家会在应用里
 * 点半天没反应,然后打客服说打印机坏了。
 */
export class BtPrinter {
  private static ctx: common.Context | null = null;

  /** 当前已连上的 socket。-1 = 没连 */
  private static socketId: number = -1;

  /** 应用启动时叫一次,给个 Context 存首选项 */
  static init(context: common.Context): void {
    BtPrinter.ctx = context;
  }

  private static async store(): Promise<preferences.Preferences> {
    const ctx: common.Context | null = BtPrinter.ctx;
    if (ctx === null) {
      throw new Error('BtPrinter 没 init');
    }
    return preferences.getPreferences(ctx, STORE);
  }

  // ---------- 设备记忆 ----------

  static async savedDevice(): Promise<PairedDevice | null> {
    const p: preferences.Preferences = await BtPrinter.store();
    const addr: string = await p.get(K_ADDR, '') as string;
    if (addr.length === 0) {
      return null;
    }
    const name: string = await p.get(K_NAME, '') as string;
    return { addr: addr, name: name.length > 0 ? name : addr };
  }

  static async saveDevice(addr: string, name: string): Promise<void> {
    const p: preferences.Preferences = await BtPrinter.store();
    await p.put(K_ADDR, addr);
    await p.put(K_NAME, name);
    await p.flush();
  }

  static async clearDevice(): Promise<void> {
    const p: preferences.Preferences = await BtPrinter.store();
    await p.delete(K_ADDR);
    await p.delete(K_NAME);
    await p.flush();
    BtPrinter.disconnect();
  }

  /** 来单自动打印(默认开;仅在已选过打印机时生效) */
  static async autoPrintEnabled(): Promise<boolean> {
    const p: preferences.Preferences = await BtPrinter.store();
    const on: boolean = await p.get(K_AUTO, true) as boolean;
    const device: PairedDevice | null = await BtPrinter.savedDevice();
    return on && device !== null;
  }

  static async setAutoPrint(on: boolean): Promise<void> {
    const p: preferences.Preferences = await BtPrinter.store();
    await p.put(K_AUTO, on);
    await p.flush();
  }

  // ---------- 设备列表 ----------

  /**
   * 系统里已配对的设备。
   *
   * 蓝牙没开时抛中文异常 —— 商家看到「蓝牙未开启」比看到错误码有用。
   */
  static async pairedDevices(): Promise<PairedDevice[]> {
    let state: connection.BluetoothState;
    try {
      state = connection.getState();
    } catch (e) {
      hilog.warn(DOMAIN, TAG, '取蓝牙状态失败 %{public}s',
          JSON.stringify(e as BusinessError));
      throw new Error('这台设备的蓝牙用不了');
    }
    if (state !== constant.BluetoothState.STATE_ON) {
      throw new Error('蓝牙未开启,请先打开手机蓝牙');
    }
    const addrs: string[] = connection.getPairedDevices();
    const out: PairedDevice[] = [];
    for (let i: number = 0; i < addrs.length; i++) {
      const addr: string = addrs[i];
      let name: string = addr;
      try {
        name = connection.getRemoteDeviceName(addr);
      } catch (_) {
        // 拿不到名字就用地址顶着。**不能因此把这台设备藏起来** ——
        // 藏了商家就选不到他那台机器了
      }
      out.push({ addr: addr, name: name });
    }
    return out;
  }

  // ---------- 连接与写入 ----------

  private static connect(addr: string): Promise<number> {
    return new Promise<number>((resolve, reject) => {
      const option: socket.SppOptions = {
        uuid: SPP_UUID,
        secure: true,
        type: socket.SppType.SPP_RFCOMM,
      };
      socket.sppConnect(addr, option, (err: BusinessError, id: number) => {
        if (err !== null && err !== undefined && err.code !== 0) {
          reject(err);
          return;
        }
        resolve(id);
      });
    });
  }

  private static disconnect(): void {
    if (BtPrinter.socketId < 0) {
      return;
    }
    try {
      socket.sppCloseClientSocket(BtPrinter.socketId);
    } catch (_) {
      // 本来就没连上/已经断了都会抛。目的只是把连接状态清干净好重连,
      // 断不成功不影响下一次重连(下面会重新 sppConnect)
    }
    BtPrinter.socketId = -1;
  }

  /**
   * 写字节流;断连自动重连重试一次。
   *
   * 返回 null = 成功;其他 = **中文**错误提示。
   *
   * 中间那一轮的异常故意吞掉:还有第二次机会时报错等于骗人。
   * 两轮都没成才给下面那句话。
   */
  private static async write(addr: string, bytes: number[]):
      Promise<string | null> {
    const buf: ArrayBuffer = new ArrayBuffer(bytes.length);
    const view: Uint8Array = new Uint8Array(buf);
    for (let i: number = 0; i < bytes.length; i++) {
      view[i] = bytes[i] & 0xFF;
    }

    for (let attempt: number = 0; attempt < 2; attempt++) {
      try {
        if (BtPrinter.socketId < 0) {
          BtPrinter.socketId = await BtPrinter.connect(addr);
        }
        socket.sppWrite(BtPrinter.socketId, buf);
        return null;
      } catch (e) {
        hilog.warn(DOMAIN, TAG, '打印第 %{public}d 轮失败 %{public}s',
            attempt + 1, JSON.stringify(e as BusinessError));
        BtPrinter.disconnect();
      }
    }
    return '打印失败,请重试(打印机可能被其他设备占用)';
  }

  // ---------- 打印 ----------

  /** 打订单小票。null = 成功;[NO_DEVICE] = 没选过打印机;其他 = 中文提示 */
  static async printOrder(order: MerchantOrder, shopName: string):
      Promise<string | null> {
    const device: PairedDevice | null = await BtPrinter.savedDevice();
    if (device === null) {
      return NO_DEVICE;
    }
    return BtPrinter.write(device.addr, orderTicket(order, shopName));
  }

  /** 打测试页。商家连好机器后先打一张,确认通路 */
  static async printTest(shopName: string): Promise<string | null> {
    const device: PairedDevice | null = await BtPrinter.savedDevice();
    if (device === null) {
      return NO_DEVICE;
    }
    return BtPrinter.write(device.addr, testTicket(shopName));
  }
}
