import { common, Want } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';

/**
 * 两点距离与「用系统地图导航」。
 *
 * ## 为什么不接地图 SDK
 *
 * 华为 Map Kit 和腾讯的鸿蒙地图都要开发者账号 + AGC 配置(和推送同一个卡点)。
 * 但商家在自送和查骑手位置这两个场景里,真正需要的是两件事:
 *
 * 1. **多远** —— 决定这单自不自送;
 * 2. **怎么去** —— 而这件事系统地图做得比我们内嵌的好。
 *
 * 所以这一版给距离 + 拉起系统地图导航。**这不是降级方案** ——
 * 商家本来也要切到高德/百度才能真正导航,内嵌地图只是多看一眼。
 * 等地图 SDK 接上再补轨迹。
 */

/** 地球半径(米) */
const R: number = 6371000;

function rad(d: number): number {
  return d * Math.PI / 180;
}

/** 两点直线距离(米)。和服务端 `haversine_m` 同一个公式 */
export function distanceMeters(lat1: number, lng1: number,
                               lat2: number, lng2: number): number {
  const dLat: number = rad(lat2 - lat1);
  const dLng: number = rad(lng2 - lng1);
  const a: number = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(rad(lat1)) * Math.cos(rad(lat2)) *
      Math.sin(dLng / 2) * Math.sin(dLng / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * 拉起系统地图导航到某个坐标。
 *
 * 走 `geo:` scheme,装了任意地图应用都能接住。**失败要照实说** ——
 * 不能点了没反应,商家会以为应用卡了。
 */
export function navigateTo(context: common.UIAbilityContext,
                           lat: number, lng: number, label: string): void {
  const name: string = encodeURIComponent(label);
  const want: Want = {
    action: 'ohos.want.action.viewData',
    entities: ['entity.system.browsable'],
    uri: `geo:${lat},${lng}?q=${lat},${lng}(${name})`,
  };
  context.startAbility(want).catch(() => {
    promptAction.showToast({ message: '没找到地图应用,装一个高德或百度地图再试' });
  });
}
