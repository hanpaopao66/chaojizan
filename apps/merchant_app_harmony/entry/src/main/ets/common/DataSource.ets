/**
 * `LazyForEach` 用的数据源。
 *
 * ## 为什么非要它不可
 *
 * `ForEach` 会把所有子项一次性建出来。商家端最长的几个列表是订单、菜品、
 * 评价、流水 —— 午高峰订单几十条、菜单上百道,一次性建完首帧就卡,
 * **而卡的时候商家正在接单**。
 *
 * `LazyForEach` 只建可见区域附近的那几个,但它要求数据源实现
 * `IDataSource`。这个类就是那份样板,三端列表共用一份。
 *
 * ## 用法
 *
 * ```typescript
 * private ds: ArrayDataSource<MerchantOrder> = new ArrayDataSource();
 * // 数据变了:
 * this.ds.reload(list);
 * // 界面:
 * LazyForEach(this.ds, (o: MerchantOrder) => { ... }, (o) => o.order_no)
 * ```
 *
 * `reload` 走的是整体刷新(`notifyDataReload`)。**没做逐项 diff 是有意的**:
 * 商家端的列表每次都是整份重拉,逐项 diff 的收益抵不上写错的风险 ——
 * diff 写错的表现是「列表里少了一单」,那是这个应用最不能出的错。
 */
export class ArrayDataSource<T> implements IDataSource {
  private items: T[] = [];
  private listeners: DataChangeListener[] = [];

  totalCount(): number {
    return this.items.length;
  }

  getData(index: number): T {
    return this.items[index];
  }

  registerDataChangeListener(listener: DataChangeListener): void {
    if (this.listeners.indexOf(listener) < 0) {
      this.listeners.push(listener);
    }
  }

  unregisterDataChangeListener(listener: DataChangeListener): void {
    const i: number = this.listeners.indexOf(listener);
    if (i >= 0) {
      this.listeners.splice(i, 1);
    }
  }

  /** 换一整份数据 */
  reload(items: T[]): void {
    this.items = items;
    for (let i: number = 0; i < this.listeners.length; i++) {
      this.listeners[i].onDataReloaded();
    }
  }

  /** 翻页追加:只通知新增的那一段,已经建好的不重建 */
  append(more: T[]): void {
    const from: number = this.items.length;
    this.items = this.items.concat(more);
    for (let i: number = 0; i < this.listeners.length; i++) {
      for (let j: number = 0; j < more.length; j++) {
        this.listeners[i].onDataAdd(from + j);
      }
    }
  }

  get all(): T[] {
    return this.items;
  }
}
