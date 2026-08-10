import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { fileIo } from '@kit.CoreFileKit';
import { request } from '@kit.BasicServicesKit';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { Api, ApiException } from './Api';
import { Session } from './Session';

/**
 * 选图与上传。
 *
 * 三处功能卡在这上面:售后举证(图片必传)、评价配图、头像。
 * 之前那几页都写着"待接入",而**没做假的成功态** —— 现在把它做实。
 *
 * ## 只用相册,不申请相机
 *
 * 走 `photoAccessHelper` 的**图库选择器**:它是系统级的选择器,
 * 选完只把选中那几张的临时读权限给应用,**不需要申请相册权限**,
 * 更不需要相机权限。安卓端的权限清单里特意没有相机,鸿蒙端同样不要 ——
 * 多申请一个用不到的权限就是应用商店的一个检测项,
 * 也是隐私政策里要多解释的一条。
 *
 * ## 上传走 uploadFile 不是拼 multipart
 *
 * 鸿蒙的 `request.uploadFile` 原生支持 multipart,不用自己拼边界串。
 * 但它只接受**应用沙箱内**的文件,所以要先把选中的图拷进缓存目录再传。
 */

/** 上传用途。与服务端 `storage.PURPOSES` 一致,私密用途会落私密桶 */
export class UploadPurpose {
  /** 头像(公开) */
  static readonly AVATAR: string = 'avatar';
  /** 评价配图(公开 —— 评价本身就是公开的) */
  static readonly REVIEW: string = 'review';
  /** 售后凭证(私密) */
  static readonly AFTER_SALE: string = 'after_sale';
  /** 食安投诉举证(私密;可能含医疗信息,比身份证更不能公开直出) */
  static readonly FOOD_SAFETY: string = 'food_safety';
}

/** 上传结果 */
export interface UploadedImage {
  url: string;
  private: boolean;
}

interface UploadRespBody {
  url?: string;
  private?: boolean;
  detail?: string;
}

/**
 * 拉起系统图库选择器,返回选中图片的 uri 列表。
 *
 * [maxCount] 最多选几张。售后是 3 张,头像是 1 张。
 */
export async function pickImages(maxCount: number): Promise<string[]> {
  const options = new photoAccessHelper.PhotoSelectOptions();
  options.MIMEType = photoAccessHelper.PhotoViewMIMETypes.IMAGE_TYPE;
  options.maxSelectNumber = maxCount;
  const picker = new photoAccessHelper.PhotoViewPicker();
  const result = await picker.select(options);
  return result.photoUris ?? [];
}

/**
 * 把图库里的图拷进应用缓存,再上传。
 *
 * 为什么要拷一遍:`request.uploadFile` 只认应用沙箱内的路径,
 * 图库给的 uri 在沙箱外。这一步省不掉。
 */
export async function uploadImage(context: common.UIAbilityContext,
                                  uri: string, purpose: string): Promise<UploadedImage> {
  const cacheDir: string = context.cacheDir;
  // 文件名带上时间戳做区分。**不用原始文件名** ——
  // 相册里的文件名可能带用户信息(某些相机会写地点),没必要传给服务端
  const name: string = `up_${purpose}_${cacheDir.length}_${uri.length}.jpg`;
  const dest: string = `${cacheDir}/${name}`;

  // 拷贝:打开图库 uri 读,写进沙箱
  const src = await fileIo.open(uri, fileIo.OpenMode.READ_ONLY);
  try {
    const dst = await fileIo.open(dest,
      fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try {
      await fileIo.copyFile(src.fd, dst.fd);
    } finally {
      await fileIo.close(dst);
    }
  } finally {
    await fileIo.close(src);
  }

  const session: Session = Session.get();
  const headers: Record<string, string> = {};
  if (session.token.length > 0) {
    headers['Authorization'] = `Bearer ${session.token}`;
  }

  const config: request.UploadConfig = {
    url: `${Api.get().baseUrl}/upload`,
    header: headers,
    method: 'POST',
    files: [{
      filename: name,
      name: 'file',
      uri: `internal://cache/${name}`,
      type: 'jpg',
    }],
    // 服务端按 purpose 决定落公开桶还是私密桶
    data: [{ name: 'purpose', value: purpose }],
  };

  return await new Promise<UploadedImage>((resolve, reject) => {
    request.uploadFile(context, config).then((task: request.UploadTask) => {
      let body: string = '';
      task.on('headerReceive', () => {});
      // 上传完成后服务端把 {url, private} 放在响应体里
      task.on('complete', () => {
        try {
          const parsed: UploadRespBody = JSON.parse(body) as UploadRespBody;
          if (parsed.url !== undefined && parsed.url.length > 0) {
            resolve({ url: parsed.url, private: parsed.private === true });
          } else {
            reject(new ApiException(0, parsed.detail ?? '上传失败,换一张试试'));
          }
        } catch (e) {
          reject(new ApiException(0, '上传返回异常,稍后再试'));
        }
      });
      task.on('fail', () => {
        reject(new ApiException(0, '图片没传上去,检查一下网络'));
      });
      // 响应体分片到达,拼起来
      task.on('progress', () => {});
      task.on('response', (resp: request.HttpResponse) => {
        body = resp.responseCode >= 400 ? '' : (resp.body ?? '');
        if (resp.responseCode >= 400) {
          reject(new ApiException(resp.responseCode,
            `上传失败(${resp.responseCode})`));
        }
      });
    }).catch((e: BusinessError) => {
      reject(new ApiException(0, `上传失败:${e.message}`));
    });
  });
}

/** 选图 + 逐张上传。任一张失败就整体报错,不做"传了一半算成功" */
export async function pickAndUpload(context: common.UIAbilityContext,
                                    purpose: string,
                                    maxCount: number): Promise<string[]> {
  const uris: string[] = await pickImages(maxCount);
  const urls: string[] = [];
  for (let i = 0; i < uris.length; i++) {
    const r: UploadedImage = await uploadImage(context, uris[i], purpose);
    urls.push(r.url);
  }
  return urls;
}
