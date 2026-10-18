# 精品游戏标准(官方小程序 · 小游戏)

这份标准管的是**已经上架和准备上架的官方游戏**:策划、数值、画面、音效、交互、无障碍、工程、
测试、发布。它不是愿望清单,是**验收判据** —— 每条后面跟着「怎么验」,能自动化的都接进了
`scripts/check_miniapp_meta.mjs`(静态)和 `scripts/qa_miniapps.mjs`(无头浏览器)。

适用对象:`miniapps/` 下所有 `kind="game"` 的应用(2048、贪吃蛇、方块消除、扫雷、五子棋、
萌兽三路、方块原野、星火牌局、突击时刻、瓜田防线),以及以后新加的官方游戏。
老的小游戏按「结构项必过、深度项逐步补齐」处理,新游戏从第一版起全量适用。

## 1. 策划(Planning)

| 必须 | 怎么验 |
|---|---|
| 一局/一关有明确的**目标、失败条件、结束与重开路径**;关掉再开能继续(或明确说明不保存进行中的一局) | 浏览器走一遍:开始→输/赢→重开→回首页 |
| **新手能上手**:首局有内联提示,操作说明页能查到全部操作 | 截图 + 操作说明页存在 |
| **进度感**:关卡/卡组/成就/战绩至少有一种跨局保留;没有「必须一直在线」的机制 | 存档往返测试 |
| 不做广告、内购、抽卡、排行榜、多人、外链;不申请敏感能力 | 静态扫描 + listing 文案 |
| 「关于」页如实写:做什么、不做什么、数据存哪、原创声明 | 人工检查 |
| 文案全中文、无错别字;不用商业游戏的名字/角色/素材 | 人工检查 + `ASSETS.md` |

## 2. 数值(Numbers / Balance)

| 必须 | 怎么验 |
|---|---|
| 所有数值集中在数据文件(`data.ts` / `types.ts`),逻辑代码里不出现魔法数 | code review + 数据自检测试 |
| **难度曲线**:开局容易、中段加压、Boss/结算有变化;至少两档难度或一条可赢的基准策略 | 关卡/对局可赢性模拟测试(固定种子) |
| **不软锁**:金币/血量/卡牌不会因为一次失误导致必定输且无解;失败后能重开 | 模拟 + 人工试玩 |
| 经济不自相矛盾(奖励 ≥ 必要消耗的可达性;不存在无限刷) | 纯函数经济测试 |
| 平衡改动有据:平衡参数变更时同步 update 测试里的基准策略 | PR/commit 说明 |

## 3. 画面(Visuals)

| 必须 | 怎么验 |
|---|---|
| 统一品牌色板:骨白/墨/黏土,每游戏可有自己的主题色;亮暗两套都能读 | 暗色截图 |
| 文本对比度 ≥ 4.5:1;颜色之外还有形状/图标区分状态(不只靠红绿) | 人工检查 + 截图 |
| 分辨率无关:canvas 按 devicePixelRatio 缩放,360–430px(竖屏)/640–900px(横屏)不溢出、不遮挡 | 两档视口截图 + `scrollWidth/Height` 检查 |
| 关键动效 120–260ms、有缓动;`prefers-reduced-motion` 时关闭位移/震动/粒子 | 减少动态截图 |
| 美术**原创 + 程序化**(Canvas/SVG/CSS/WebAudio),零外部图片/字体/音频;每游戏有 `ASSETS.md` | 静态扫描 + zip 内容检查 |
| 空状态/加载/失败页不空白;loading 有反馈 | 截图 |

## 4. 音效(Audio)

| 必须 | 怎么验 |
|---|---|
| 每个关键交互有反馈音:按钮、成功、失败、核心动作(射击/出牌/挖放/放塔) | 人工试听清单 + 代码检查 |
| 音效**全部 WebAudio 合成**,无音频文件;首次用户交互后解锁 AudioContext | 静态扫描 + 浏览器 console 无警告 |
| 有静音开关,状态持久化;切后台/暂停时 BGM 暂停(有 BGM 的游戏) | 存档往返 + 浏览器检查 |
| 音量不刺耳:峰值不削波,长音不叠加爆音;多个音效同时响时有限并发 | 人工试听 + 代码 review |
| 可选:轻量 BGM 循环(合成),按主题/模式切换 | 人工试听 |

## 5. 交互与无障碍(UX / A11y)

| 必须 | 怎么验 |
|---|---|
| 点击目标 ≥ 44×44px;真 `<button>`;有 `:focus-visible` 样式 | 静态检查 + 键盘走查 |
| 关键状态用 `aria-live` 播报(回合、得分、胜负、存读档) | 每个游戏至少 1 个 `[aria-live]` |
| 桌面可键盘玩(或至少有键盘等价操作);手机触屏可玩 | 无头浏览器键盘 + 触摸模拟 |
| 暂停/继续/重开/回首页都能走通;**切后台自动暂停 + 立刻存档** | 浏览器 visibility 事件测试 |
| 弹层打开时**焦点圈在弹层里**、背景 `inert`(Touch/Tab/读屏都不能穿到后面的游戏);关闭后焦点回到打开前的位置 | `shared/src/ui.ts` 的 `Overlay` 已统一实现,浏览器 Tab 走查 |
| 宿主返回键行为正确:弹层→关弹层,局内→暂停,首页→宿主处理;不把人困住 | 浏览器模拟 BackButton |
| 安全区:顶部避开胶囊、底部避开横条(`base.css` 的 `--top/--bottom/--side`) | 截图 + CSS 检查 |

## 6. 工程(Engineering)

| 必须 | 怎么验 |
|---|---|
| `miniapps/<app>/` 结构:`index.html`、`public/superz.json`、`listing.json`、`src/*`、`test/*`、`ASSETS.md` | `check_miniapp_meta.mjs` |
| 纯逻辑与界面分离;单文件 ≤ ~700 行;strict TS;无 `any`(除非有注释);无 `console.log` | tsc + 静态扫描 |
| 帧率无关循环(`dt` 上限、暂停/隐藏不推进、不叠加 rAF);目标 60fps | 浏览器帧率测量 |
| 存档走 `SaveSlot`:`cacheKey` 带 open_id;单值 ≤ 64KB;坏档容错;合并语义正确 | 单测 + 浏览器刷新续档 |
| 无内联 `<script>`、无外部请求、无 `eval`;CSP 兼容;zip < 400KB(小游戏 < 30MB 上限内自己要求更严) | 浏览器请求检查 + 静态扫描 |
| 生产构建不含调试钩子/开发便利(`import.meta.env.DEV` 包住,构建后 grep 为 0) | 构建后 grep |
| 元数据:`listing.json` 字段齐全、版本号/changelog 与本次改动一致;`superz.json` 的 sdk/kind/orientation 正确 | `check_miniapp_meta.mjs` |

## 7. 测试与验收(Testing)

| 必须 | 怎么验 |
|---|---|
| 纯函数单测:关键不变量(可复现、边界、存档、经济/胜负)≥ 20 条(小游戏 ≥ 10) | `node scripts/test.mjs <app>` |
| 平衡/可赢性:固定种子模拟能赢(关卡类给基准策略;Boss 关单独验证) | 单测 |
| 无头浏览器冒烟:菜单→开局→核心操作→结算/暂停→关于→刷新续档;两种视口 + 亮暗 + reduced-motion | `node scripts/qa_miniapps.mjs <app>` |
| console error 0、外部请求 0、内联脚本 0、无横向溢出、fps ≥ 50(headless 参考值) | 同上(自动断言) |
| 发布前:`build_miniapp.sh` 可复现 SHA、`validate_package` 通过、线上 appid/SHA 核对 | 发布清单 |

## 8. 发布(Publishing)

1. 改 `listing.json` 的 `version` 与 `changelog`(用户看得到);同步 `docs/MINIAPP-GAMES.md`;
2. `bash scripts/build_miniapp.sh <app>` → 记下 SHA-256,连续两次一致;
3. `node scripts/check_miniapp_meta.mjs <app>`、`node scripts/qa_miniapps.mjs <app>` 全绿;
4. **先看计划**(不写库、不传对象):

   ```sh
   scripts/publish_miniapps.sh <app>            # 自动走部署机/容器,跑的是同一个发布脚本
   ```

   确认后加 `--apply` 真发布(新应用会自动建 appid;已有应用发新版本并自动发布):

   ```sh
   scripts/publish_miniapps.sh --apply <app>
   ```

   脚本在 api 容器里用 `server/scripts/publish_official_miniapps_batch.py` 批量发布,审核人 =
   第一个管理员,发布完自动跑 `deploy/mp-cert.sh` 把新 appid 签进托管证书(没变化就跳过);
5. 线上复核:目录、详情页、托管页 200 + CSP、TLS、无头 Chrome 从线上域名打开;
6. 回滚:发布新版本/回滚到上一版本;单个版本有问题用「紧急隔离」。

## 9. 自动化入口

```sh
cd miniapps
node scripts/check_miniapp_meta.mjs          # 静态:结构/metadata/无外部素材/无内联脚本/大小
npm run typecheck && npm test                # 全量类型检查 + 纯函数单测
node scripts/qa_miniapps.mjs                 # 无头浏览器:全部应用(需先 build 或 dev)
scripts/publish_miniapps.sh <app>            # 发布:先看计划;加 --apply 真发布(需部署机可达)
```

`check_miniapp_meta.mjs` 接入 `make analyze` 与 CI;`qa_miniapps.mjs` 因为依赖本机 Chrome,
作为发布前的手动门禁(发布清单第 3 步),不进 CI。
