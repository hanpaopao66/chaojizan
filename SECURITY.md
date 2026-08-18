# 安全政策

这是一个碰钱的系统。发现漏洞请私下报告,别让它先出现在公开 issue 里。

## 怎么报告

- 邮箱:**support@chaojizan.cc**(标题带「安全」两个字)
- 或 GitHub 的 [私密漏洞报告](https://github.com/hanpaopao66/chaojizan/security/advisories/new)
  (Security → Report a vulnerability)

**必回时限:72 小时内给出初步回应**,修复排期在回应里说清楚。
这和骑手意见反馈「平台必须回复」是同一条纪律,对报告漏洞的人只会更严。

**赏金:没有。** 平台三原则决定了没有这笔预算(5% 是唯一收入,盈余优先
骑手保障)。我们能给的是:修复公告里署名致谢(你愿意的话)、
以及认真对待每一份报告。先说清楚,免得浪费你的期待。

修复后的披露:影响资金或个人信息的漏洞,修复上线后会在
[透明中心·变更留痕](https://chaojizan.cc/transparency#changelog) 公示
(不含利用细节)。

## 范围

- 本仓库全部代码(后端、三端 App、商家工作台、官网、见证节点)
- 官方实例 `chaojizan.cc` 及其子路径

**不在范围**:对官方实例的压测/扫描/DoS(会影响真实商家的真实订单,
请在自己部署的环境里测);社会工程;需要物理接触设备的攻击。
测试涉及真实下单的,用文档里的演示账号,别拿真商家练手。

## 威胁模型:我们想过什么、防了什么、没防什么

按「样本不足就说不足」的口径:防了的给代码坐标,没防的直说没防。

### 有对抗的

| 攻击面 | 对抗手段 | 代码位置 |
|---|---|---|
| 篡改历史账目 | 哈希链锚点永不重算 + 社区见证节点独立留存复算,协议见 [docs/LEDGER-SPEC.md](docs/LEDGER-SPEC.md) | `server/app/services/ledger.py` |
| 钱包双花 / 并发提现 | 行锁串行化,余额校验在锁内 | `server/app/routers/riders.py` `request_withdrawal()` |
| 抢单冲突 / 超卖 | 条件 UPDATE,并发安全在存储层 | `riders.py` `grab_order()`、`orders.py` 库存扣减 |
| 支付回调伪造 / 重放 | 微信 V3 验签 + 回调金额与订单金额核对 + 幂等入账(已支付即短路) | `server/app/services/payment_core.py` `mark_order_paid()` |
| 白嫖下单(模拟支付) | `MOCK_PAY_ENABLED=false` 是生产硬开关,`/admin/readiness` 自检项 | `server/app/routers/platform.py` `_readiness_rows()` |
| 非法状态流转 | 状态机唯一入口,非法流转 409,全量审计表 | `server/app/state_machine.py` |
| 刷单 / 刷评 | 反作弊闭环:标记不拦截、分级处置可申诉;差评不删、刷评标记不隐藏 | `server/app/services/` 风控相关 |
| 验证码轰炸 | 同 IP 每日 20 条、同号每日 8 条、第 3 条起滑块 | `server/app/routers/auth.py` |
| 证照/身份证图片泄露 | 私密桶不可匿名读,只能过判权接口回读;nginx 故意不给私密桶配 location | `server/app/services/storage.py`,`deploy/nginx/conf.d/superz.conf` |
| 公开数据反推个人 | 大屏/透明中心全聚合、手机号打码、坐标两位小数、账本单号哈希匿名化 | `server/app/routers/screen.py`、`ledger.py` |
| 密钥进仓库 | 提交前 `scripts/security_scan.sh` + CI 全历史 gitleaks 双层扫描 | `.github/workflows/ci.yml` security job |
| 承诺数字被后台改掉 | 承诺类数字不做成可下发配置,admin 写入直接拒绝;费率上限进账本哈希链 | 见 docs/DEV-PROMPTS-10.md |

### 明确还没防的

写出来比藏着强 —— 这些也是最欢迎收到报告和 PR 的方向:

- **见证节点的女巫问题**:平台可以自己伪装成一堆节点撑场面。节点数是
  社会证明不是共识机制(witness/README 的诚实声明),真正的保证是
  「你自己跑的那一个」,但我们没有、短期也不打算做节点身份证明;
- **DoS / 大流量攻击**:接口限流只防误用不防攻击,没有 WAF、没有抗 D。
  起步期的量级扛不住也赔不起,先认;
- **账本漏记**:交易根本不进账本的话,验证器抓不到。缓解是用户可用
  自己的单号哈希自证在账(LEDGER-SPEC §2.3),系统性的漏记检测没有;
- **供应链**:依赖锁定不完整(Python 依赖多为 `>=` 版本),没有做
  SBOM 和依赖审计自动化;
- **号码隐私非严格模式**:`PRIVACY_PHONE_STRICT` 未开时,拨打走真实
  手机号(界面显示打码)。开关在,默认没开,因为 AXB 中间号要花钱。

## 给自部署者的底线清单

拿这套代码开自己的城,上线前至少确认(详见 [docs/OPEN-A-CITY.md](docs/OPEN-A-CITY.md)):

1. `MOCK_PAY_ENABLED=false`、`ADMIN_PASSWORD_LOGIN=false`;
2. `JWT_SECRET` 用 `openssl rand -hex 32` 生成,**上线后不可再换**
   (收款账户密文由它派生加密,换了解不开);
3. 短信必须配真的 —— 不配时验证码随接口明文返回,等于任何人可登录任意账号;
4. 跑一遍 `deploy/readiness.sh`,12 项自检全绿再开门。
