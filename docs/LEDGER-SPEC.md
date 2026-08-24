# 公开账本哈希链 · 协议规格(schema 1)

这份文档的目标读者是**想用任何语言写一个独立验证器的人**。
读完它,你应该不用读我们的任何代码,就能写出一个验证器,
并用文末的测试向量自测通过。写出来了、对得上向量,
欢迎按文末的方式把你的节点亮出来 —— 从此我们的四个实现降级为「参考实现」,
你的是「第三方实现」,后者对「社区见证」这四个字的分量大得多。

规范性用语:**必须** = 不这么做就不算实现了本协议;**应当** = 强烈建议;
**信息性** = 仅供理解,不构成校验义务。

## 0. 信任模型:这套机制能抓什么、不能抓什么

先把丑话说在前面,这比协议本身重要:

**能抓**:
- 平台改写或删除任何历史账目(哪怕一分钱)—— 链哈希断裂,所有留存过锚点的节点立刻发现;
- 任何一天的实收佣金超过该天账本自己声明的上限;
- 骑手配送费被冲账(协议规定骑手行只进不出);
- 团购/住宿服务费偏离承诺费率。

**不能抓**:
- 平台把「上限」本身写高 —— `commission_rate_max` 是平台自己写进账本的数。
  这条防线不在验证器里,在别处:上限数值本身进了不可篡改的链
  (想偷偷提高,历史上写过 0.05 的锚点就是呈堂证供),且生成代码开源、
  线上版本与仓库 tag 对应;
- 平台漏记订单(账本里根本没出现的交易)。缓解手段是知道自己单号的用户
  可以按 §3.4 的规则自证自己的单在不在账本里;
- 女巫节点(平台自己伪装成多个见证节点)。节点数只是参考信号,
  真正的保证来自**你自己跑的那一个**。

## 1. 公开接口

Base URL:部署方的公开域名(官方实例为 `https://chaojizan.cc`)。
路径为裸路径,无前缀。所有接口无鉴权。

### 1.1 `GET /ledger/anchors?after=<day>`

返回锚点列表,JSON 数组,按 `day` **升序**,每页最多 **400** 条。
元素只有三个键:

```json
{"day": "2026-06-29", "payload_hash": "<64位小写hex>", "chain_hash": "<64位小写hex>"}
```

`after` 是**开区间**字符串比较(返回 `day > after` 的锚点),省略或空串 = 从头。
翻页协议:循环拉取,返回条数 < 400 即为最后一页,否则以本页最后一条的
`day` 作为下一次的 `after`。

### 1.2 `GET /ledger/days/{day}`

返回单日全文:

```json
{"day": "...", "payload": { ... }, "payload_hash": "...", "chain_hash": "..."}
```

`day` 不存在时返回 404(未到关账时间,或早于账本起点)。

**必须注意**:`payload` 是服务端把内部存储的规范化 JSON 反序列化后、
再由 Web 框架重新序列化的 —— 键序、空白都可能变。
**验证器必须对 `payload` 对象自行做 §4 的规范化序列化后再哈希,
绝不能对 HTTP 响应原文哈希。**

### 1.3 `POST /nodes/heartbeat`(可选)

验证器**应当**在每轮校验后上报心跳,让自己出现在公开节点页。请求体:

| 字段 | 约束 | 说明 |
|---|---|---|
| `node_id` | 必填,匹配 `^[A-Za-z0-9-]{8,64}$` | 本机自生成并持久保存,是节点身份 |
| `name` | ≤30 字符 | 展示名(超长会被 422 拒绝) |
| `region` | ≤30 字符 | 展示地区 |
| `tz` | ≤40 字符 | IANA 时区名或 `UTC±HH:MM` |
| `version` | ≤20 字符 | 你的实现版本串 |
| `verified_day` | ≤10 字符 | 已校验到哪天 |
| `chain_hash` | ≤64 字符 | 该天你复算出的链哈希 |
| `ok` | bool | 本轮是否全部通过 |
| `message` | ≤200 字符 | 出问题时的一句话说明 |

响应 `{"registered": true, "divergent": bool}`。`divergent=true` 表示你报的
`chain_hash` 与平台记录不一致 —— 会在公开节点页示警,这正是设计目的。
限流:同一 `node_id` 每分钟 6 次;节点总数上限 5000。
参考实现的心跳周期为 5 分钟;15 分钟内有心跳算在线。

### 1.4 信息性接口

`GET /nodes/summary`(节点总览)、`GET /stats/overview`(趋势聚合)。
均不参与校验。注意 `/transparency/*` 是另一套运营透明接口,
直接查库聚合、**不进哈希链**,与本协议无关。

## 2. 每日 payload 结构

每个北京时间自然日(`Asia/Shanghai`)一份 payload。
**只为已过完的日子生成**(「今天」永远没有锚点);锚点生成后**永不重算**。
空账日照常生成锚点(四个数组为空、合计全 0),链不跳天、不合并。

### 2.1 顶层字段(schema 1)

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | int | 恒为 `1` |
| `day` | string | `YYYY-MM-DD`,北京时间自然日 |
| `commission_rate_max` | number | 该日承诺的外卖佣金上限(当前 `0.05`) |
| `voucher_rate` | number | 该日团购核销服务费率(当前 `0.02`) |
| `stay_rate` | number | 该日住宿佣金率(当前 `0.05`) |
| `merchant_rows` | array | 商家账行 |
| `rider_rows` | array | 骑手账行 |
| `voucher_rows` | array | 团购核销行 |
| `stay_rows` | array | 住宿账行 |
| `rider_fund` | object | 骑手保障金池:`{per_order_cents, orders, accrued_cents}` |
| `totals` | object | 七项合计,见 §6.5 |

三个费率字段是**该日口径的冻结值**:降费率只影响之后的新锚点,
历史锚点里的旧费率永久不变,验证器按锚点自带的费率复算(§8)。

### 2.2 行结构

金额一律为**整数,单位「分」**。

```jsonc
// merchant_rows 每行
{"o": "<24位hex>", "food": 900, "commission": 45, "net": 855, "kind": "earning"}
// kind ∈ {"earning", "reversal", "adjustment"}

// rider_rows 每行
{"o": "<24位hex>", "amount": 500, "kind": "earning"}

// voucher_rows 每行(只含已核销)
{"p": "<24位hex>", "gross": 5000, "fee": 100, "net": 4900}

// stay_rows 每行
{"s": "<24位hex>", "gross": 20000, "fee": 1000, "net": 19000, "kind": "settle"}
// kind ∈ {"settle", "cancel", "noshow", "penalty"}
```

住宿只记有资金流的行:离店结算(`settle`)、有留存的取消/未入住
(`cancel`/`noshow`)、到店无房违约金(`penalty`,商家负行)。
全额退、零资金流的取消**不进账本**。

**行序由平台决定,验证器不校验行序**(信息性:三个数组按内部自增 id,
`stay_rows` 按单号哈希字典序)—— 行序被哈希锁定,无法事后调整,
但顺序本身不承载业务含义。

### 2.3 匿名化与自证

`o` / `p` / `s` 是单号的匿名化标识:

```
sha256(单号原文的 UTF-8 字节) 的小写 hex 前 24 位
```

payload 中**必须不出现**手机号、地址、姓名、用户/商家/骑手 id、经纬度、
单号原文。知道自己单号的用户,可以自己算哈希去账本里找到那一行 ——
这是「个体可自证,外人不可反推」的设计。

## 3. 规范化序列化(canonical JSON)

payload 的哈希输入是它的规范化 JSON 文本,规则**必须**逐条满足:

1. 对象的键按 **Unicode 码点升序**排序,递归应用到所有层级;
2. 分隔符为 `,` 和 `:`,**不含任何空白字符**;
3. 非 ASCII 字符**原样输出**(不做 `\uXXXX` 转义),文本按 **UTF-8** 编码成字节;
4. 不转义 `<`、`>`、`&`(某些语言的 JSON 库默认做 HTML 转义,必须关掉);
5. 整数序列化为不带小数点的十进制;费率是 payload 中仅有的非整数,
   序列化为**最短往返十进制**(`0.05`、`0.02` —— Python `json.dumps`、
   Go `encoding/json`、JS `JSON.stringify` 的默认行为一致);
6. 末尾无换行、无 BOM。

等价的 Python 定义(也是服务端生成时用的):

```python
canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

## 4. 哈希与链

```
payload_hash = sha256( canonical(payload) 的 UTF-8 字节 ) 的小写 hex(64 字符)
chain_hash   = sha256( prev_chain_hash + payload_hash )    的小写 hex(64 字符)
```

**关键细节**:第二行的 `+` 是**hex 字符串拼接** —— 哈希输入是
128 个 ASCII 字符(即 128 字节),**不是** 32+32 字节的二进制拼接。
独立实现最容易在这里「顺手优化」成二进制,务必对着测试向量检查。

创世值:链上第一天的 `prev_chain_hash` 为 64 个 ASCII 字符 `'0'`:

```
GENESIS = "0000000000000000000000000000000000000000000000000000000000000000"
```

### 4.1 链重启与纪元(规范性)

链有可能被重新起头 —— 历史上发生过一次:2026-07-28 清理生产环境的演示
数据时,脚本按当时的设计清空了全部锚点,链从新的第一天以 GENESIS 重起。

这对验证器表现为「本地留存的锚点在平台上消失」。本规范此前写的是
「按 §7 示警即可,**由人来判断**是公告过的重置还是真的在毁账」——
而这是个缺口:**机器没有任何判断依据**。实际后果是官方节点从那天起
每 5 分钟报一次警,报了 9000 多次,一个月内没有人做过那个判断,
而警报一旦长期为真就等于失效:真出事时也没人会再看它。

所以补上机器可读的依据。

**服务端必须**在重启链之前,把上一条链的以下信息写入一条**永不修改的
公开纪元记录**(`GET /ledger/epochs`):

| 字段 | 含义 |
|---|---|
| `epoch` | 纪元号,从 1 递增 |
| `started_day` | 本纪元第一个锚点的日子 |
| `reason` | 为什么重启。**不得为空**,会原样公开 |
| `prev_tip_hash` | 上一纪元的链尾 `chain_hash`(旧链每日锚点可以没了,但它最后长什么样必须留下) |
| `prev_first_day` / `prev_last_day` | 上一纪元覆盖的日期范围 |

**验证器必须**:

1. 把纪元记录**和锚点一样留存并比对** —— 记录被改或消失,同样判为篡改。
   少了这一条,平台就能事后编一条纪元来解释任何一次删账;
2. 仅当某天落在**某条已公告纪元的 `prev_first_day`~`prev_last_day`
   范围内**时,才把该天锚点的消失判为「已公告的重置」而非篡改;
   范围外一律照旧示警;
3. 即便判为已公告的重置,**也必须把它写进上报的 `message`** ——
   静默吞掉一次重置,和当初没有记录一样坏;
4. 服务端不提供 `/ledger/epochs`(旧版本)时,行为**退回**到本节之前:
   一切消失都判为篡改。宁可误报,不可漏报。

**这不是赦免。** 平台仍然改不了历史;纪元记录只是把「重启」从一个无法
解释的异常,变成一条必须署名、永久留档、验证器也会盯着的记录。

第 1 纪元的 `prev_tip_hash` 是**空的** —— 2026-07-28 那次确实没有保留
旧链链尾,现在也编不出来。这一栏空着本身就是记录的一部分。

官方实例当前这条链起于 `2026-06-29`。

### 4.2 演示数据(信息性)

一个刚部署起来的实例通常灌了演示数据,那些演示订单的流水**会照常进账本**。

这是有意的:账本的保证是「**当天全部**账务流水」,没有例外条款。
按手机号段之类的规则把某些流水悄悄漏掉,等于在完整性上开一个
外人看不见的口子 —— 而看不见的例外正是这份规格要消灭的东西。

演示数据的正解是**在真正开始运营前清掉它**(`scripts/scrub_demo.py`),
而不是让账本假装没看见。清理**不需要、也不应当**动账本:
锚点存的是当天 payload 的全文快照,底层单据删掉之后照样自洽。

## 5. 获取与留存协议

验证器**必须**:

1. 本地持久留存见过的 `{day: chain_hash}` 映射 —— 这是全部对抗能力的来源,
   丢了就只剩「相信平台当前给的」;
2. 每轮先全量拉 `/ledger/anchors` 与本地留存比对:
   - 同一天哈希变了 → **锚点被改**,示警;
   - 本地有、平台没有 → **锚点消失**,示警;
3. 对未见过的日子逐日拉 `/ledger/days/{day}` 全文,复算
   `payload_hash` 与 `chain_hash`,与锚点比对,不一致即示警并停止推进;
4. 对每天的 payload 执行 §6 的逐行核账。

**应当**:限制单轮处理天数(参考实现:60 天/轮)与问题数熔断(20 条即停),
避免半夜把 CPU 吃满;发现示警后保留现场,不覆盖本地留存。

## 6. 逐行核账(规范性)

费率**必须从当日 payload 内读取**;字段缺失时(早期锚点)使用规定的
历史默认值,这些默认值是规范的一部分:

| 字段 | 缺失时的默认 |
|---|---|
| `commission_rate_max` | `0.06` |
| `voucher_rate` | `0.03` |
| `stay_rate` | `0.05` |

以下所有比较均为整数精确比较,标注了容忍的除外。

### 6.1 商家行

```
net == food - commission                        (净额恒等式,单行内)
abs(commission) <= abs(food) × rate_max + 1     (佣金上限,±1 分取整容忍)
```

取绝对值是为了让 `reversal`(冲账镜像负数行)通过同一比例检查。

### 6.2 骑手行 —— 配送费只进不冲

```
kind == "earning"  且  amount >= 0
```

就这两条,没有上限、没有比例 —— 配送费 100% 归骑手是平台原则,
账本里出现任何 `reversal`/`adjustment` 的骑手行或负数金额,
即为违规,**必须**示警。

### 6.3 团购行

```
fee == (gross × voucher_rate_bps) // 10000      (整数运算,向零截断)
net == gross - fee                              (精确,无容忍)
```

其中 `voucher_rate_bps = round(voucher_rate × 10000)`(0.02 → 200)。
规范口径是**精确十进制截断**;用浮点乘再截断在当前费率与金额范围内
结果一致,但**应当**用整数运算实现,别赌浮点。

### 6.4 住宿行

按 `kind` 三分支:

- `settle`:`net == gross - fee` 且 `fee <= gross × stay_rate + 1`(±1 分容忍);
- `penalty`(到店无房违约金):`fee == 0` 且 `-gross <= net < 0`;
- `cancel` / `noshow`:`fee == 0` 且 `0 <= net <= gross`。

### 6.5 合计交叉校验

规范性(必须校验)的只有两条:

```
totals.rider_amount == Σ rider_rows[].amount
totals.stay_fee     == Σ stay_rows[].fee        (字段存在时)
```

`totals` 其余字段(`merchant_net`、`platform_commission`、`voucher_fee`、
`stay_net`、`rider_fund`)以及 `rider_fund` 对象为**信息性**:
它们参与哈希(改了必被抓),但当前无实现校验其与逐行加总的一致性。
第三方实现多校验几条当然欢迎 —— 校验出不一致同样值得示警。

## 7. 版本与变更规则

1. `schema` 当前恒为 `1`。**新字段只加不改、不删**;验证器**必须**
   容忍未知字段(它们参与哈希,但不影响你已实现的校验);
2. 对已有字段的任何不兼容变更(改名、改语义、改单位)**必须**升 `schema`
   版本号,且历史锚点按其自带的 schema 校验 —— 锚点永不重算,
   这条是账本铁律的延伸;
3. 费率变更不算 schema 变更:费率随当日 payload 冻结(§2.1),
   §6 的默认值表只增不改;
4. 本规格自身的变更走仓库 PR,历史可查。

## 8. 测试向量

三组向量。你的实现**必须**三组全对。

### 向量 A · 空账日(合成)

输入 payload(此处为可读格式,哈希前须按 §3 规范化):

```json
{
  "schema": 1, "day": "2026-08-16",
  "commission_rate_max": 0.05, "voucher_rate": 0.02, "stay_rate": 0.05,
  "merchant_rows": [], "rider_rows": [], "voucher_rows": [], "stay_rows": [],
  "rider_fund": {"per_order_cents": 20, "orders": 0, "accrued_cents": 0},
  "totals": {"merchant_net": 0, "platform_commission": 0, "rider_amount": 0,
             "voucher_fee": 0, "stay_net": 0, "stay_fee": 0, "rider_fund": 0}
}
```

规范化文本(应当逐字节一致,注意顶层键序):

```
{"commission_rate_max":0.05,"day":"2026-08-16","merchant_rows":[],"rider_fund":{"accrued_cents":0,"orders":0,"per_order_cents":20},"rider_rows":[],"schema":1,"stay_rate":0.05,"stay_rows":[],"totals":{"merchant_net":0,"platform_commission":0,"rider_amount":0,"rider_fund":0,"stay_fee":0,"stay_net":0,"voucher_fee":0},"voucher_rate":0.02,"voucher_rows":[]}
```

```
payload_hash = ca98e10445044893ab8c1ff89ae137cd6cbe3c9129ebabfe5914157ca5c847b6
prev         = GENESIS
chain_hash   = 402919d8a34f92cddd6cab12fc29df5868b723ac41bb2f81bb15b1f934bbe3a2
```

### 向量 B · 真实首日(官方实例链上数据)

`GET https://chaojizan.cc/ledger/days/2026-06-29` 取完整 payload
(10 条商家行,其余数组为空)。前两行示例:

```json
{"commission":45,"food":900,"kind":"earning","net":855,"o":"fa2b827a6fab56642e362d69"}
{"commission":60,"food":1200,"kind":"earning","net":1140,"o":"04153dec32cfffad417b8e0e"}
```

```
payload_hash = 213d8e8be30a67cd071fcac6637a933619faf4feff6e851e0fc813324dd69152
prev         = GENESIS
chain_hash   = 8f48e4ba4dd011341ff4ae830b5fadb2696fd838dc1fe37e02f2903a5611b642
```

### 向量 C · 真实次日(验证链拼接)

`GET https://chaojizan.cc/ledger/days/2026-06-30`(27 条商家行):

```
payload_hash = a6ed1adce3a711c275e4c1192b57d6edcf201db3ff6fa14a029b7763cf0b8516
prev         = 8f48e4ba4dd011341ff4ae830b5fadb2696fd838dc1fe37e02f2903a5611b642
chain_hash   = 8c4c06d249272623a5f531541c1a0a9e2c3efcc29b09306b2719ceba32d573c4
```

(B、C 是生产账本,数字不会变 —— 变了就说明我们在毁账,请示警。)

## 9. 参考实现与已知差异(信息性)

第一方实现四个,规范化与哈希部分完全一致,校验覆盖有差异:

| 实现 | 位置 | 已知欠账 |
|---|---|---|
| Python | [witness/superz_witness.py](../witness/superz_witness.py) | 覆盖最全,是 §6 的蓝本 |
| Go(绿色版) | [witness/go/main.go](../witness/go/main.go) | 未做 §6.5 合计校验 |
| 网页版 | server/static/nodes.html | 未做住宿行与合计校验 |
| Flutter(App 内) | packages/shared/lib/src/witness_service.dart | 未做住宿行与合计校验 |

第三方实现以**本规格**为准,不以任何参考实现为准;
参考实现与规格冲突时,规格赢,并请给我们提 issue。

## 10. 把你的实现亮出来

写完并三组向量全对后:

1. 按 §1.3 上报心跳,你的节点会出现在
   [chaojizan.cc/nodes](https://chaojizan.cc/nodes);
2. 在仓库开 issue 附上代码链接,我们在见证节点页列出独立实现
   (语言、作者、链接)—— 对得上向量即列入,不审代码风格。
