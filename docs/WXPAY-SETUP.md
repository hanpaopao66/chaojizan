# 微信支付接入操作单(你自己做,我不碰凭据)

> **这份文档里不出现任何真实值。** API v3 密钥、商户私钥、证书序列号
> 这些东西只应该存在于两个地方:微信商户平台,和你自己的服务器。
> 不要贴进聊天、不要提交进仓库、不要截图发出来 —— 截图也算泄露。
>
> 我不接收、不代填、不代你登录商户平台。下面每一步都是你在自己的机器上做。

---

## 零、类目已定:**电商平台收付通**

这个答案决定了两条链路走哪套 API:

| | 普通服务商 | **电商平台收付通(我们走这个)** |
|---|---|---|
| 进件 | `/v3/applyment4sub/` | `/v3/ecommerce/applyments/` |
| 商家身份 | 特约商户 | **二级商户(sub_mchid)** |
| 下单 | JSAPI/APP 带 sub_mchid | **`/v3/pay/partner/transactions/app`** |
| 分账 | `/v3/profitsharing/` | **`/v3/ecommerce/profitsharing/orders`** |
| 余额/提现 | 商户自己在商户平台操作 | **可由平台调接口查余额、发起提现** |

**好消息:数据模型两套通用,不用改。** `models.py:333` 那段注释当时就写了
「进件的 API 形状取决于类目,但**要商家交的材料两套是一样的**,
所以数据模型先落地」—— 现在证明这个判断是对的,商家端已经采集好的
营业执照、法人身份证、结算账户,收付通照样是这些。

**要写的只有渠道调用那一层**,而它现在一行都没写:
`profit_sharing.py` 的 `_call_channel` **恒返回 `CHANNEL_UNIMPLEMENTED`**,
文件头注释写着「渠道本身一行都还没写(走普通服务商还是电商收付通,
取决于类目答案)」。所以没有假账 —— 这一点当时留对了。

---

## 一、先把「钱能进来」跑通,再谈进件与分账

收付通完整跑通要三步:平台自己的支付配置 → 给商家进件拿 sub_mchid →
下单带 sub_mchid 并分账。**别想一次做完**,先做第一步:

- 第一步只要 5 个配置项,**今天就能验证平台侧的验签和回调是通的**;
- 第二步要商家配合交材料、等微信审核,不是当天能好的;
- 而验签、回调地址、证书模式这三个最容易出错的地方,**第一步就会暴露**。
  等到进件完了再一起调,出问题都分不清是哪一层。

所以下面第二、三步配的是**平台自己的商户参数**(收付通里叫服务商/平台
商户号),它们和后面接进件用的是同一套凭据 —— 不是白配的。

⚠️ 但要注意:**第一步跑不了完整的一笔真实支付**。收付通下单走
`/v3/pay/partner/transactions/app`,必传 `sub_mchid`,而那时还没有
任何二级商户。所以第一步的验收标准是「自检 configured=true 且服务
起得来、日志无验签错误」,真金白银那一笔要等第六步进件出一个
二级商户之后。

---

## 二、在服务器上放证书(不经过我,也不经过仓库)

证书目录 `deploy/wxpay-certs/` 在部署脚本里是 **rsync 排除项**
(`scripts/deploy_server.sh` 第 44 行),所以:

- 它**不会被 `--delete` 清掉**;
- 本地仓库里没有它,也永远不该有;
- `server/certs/` 同时在 `.gitignore` 里。

容器挂载:`./wxpay-certs:/srv/certs:ro`(只读,见
`deploy/docker-compose.prod.yml:65`)。所以容器里看到的路径是 `/srv/certs/...`。

**你要做的**(在你自己的电脑上,ssh 到部署机):

```bash
ssh <你的部署机>
mkdir -p ~/super-z/deploy/wxpay-certs
chmod 700 ~/super-z/deploy/wxpay-certs
```

然后把从商户平台下载的证书压缩包解开,**用 scp 从你本地传上去**:

```bash
# 在你本地电脑上执行(不是在部署机上)
scp apiclient_key.pem <你的部署机>:~/super-z/deploy/wxpay-certs/
# 2024 下半年后新开的商户号会给「微信支付公钥」,有的话一起传:
scp pub_key.pem <你的部署机>:~/super-z/deploy/wxpay-certs/
```

传完在部署机上收紧权限:

```bash
chmod 600 ~/super-z/deploy/wxpay-certs/*.pem
ls -l ~/super-z/deploy/wxpay-certs/    # 确认只有你可读
```

---

## 三、在服务器上填 `.env.prod`

`deploy/.env.prod` 也是 rsync 排除项,**只存在于服务器**。

```bash
ssh <你的部署机>
nano ~/super-z/deploy/.env.prod        # 或 vim
```

加这几行(等号右边填你自己的值,**别把这份文档里的占位符照抄**):

```ini
WXPAY_APP_ID=            # 开放平台 App 的 AppID(注意不是公众号的)
WXPAY_MCHID=             # 商户号
WXPAY_API_V3_KEY=        # APIv3 密钥,32 位,商户平台自己设的那个
WXPAY_CERT_SERIAL_NO=    # 商户证书序列号
WXPAY_PRIVATE_KEY_PATH=/srv/certs/apiclient_key.pem
WXPAY_NOTIFY_URL=https://<你的域名>/payments/wechat/notify

# 只有商户平台「API 安全」页显示的是**微信支付公钥**时才填这两行;
# 显示的是平台证书就整段留空(SDK 会自动下载并缓存)
WXPAY_PUBLIC_KEY_PATH=/srv/certs/pub_key.pem
WXPAY_PUBLIC_KEY_ID=
```

⚠️ **路径写容器里的 `/srv/certs/...`,不是你在服务器上看到的
`~/super-z/deploy/wxpay-certs/...`。** 代码跑在容器里。

⚠️ 确认 `MOCK_PAY_ENABLED=false` 还在(它现在就是 false)。
微信支付配好之后如果模拟支付还开着,任何登录用户都能把订单标成已支付。

---

## 四、重启并自检

```bash
cd ~/super-z/deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d api
docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx
```

> nginx 必须最后重启:它会缓存 api 容器的旧 IP,不重启十几分钟后全站 502
> (2026-08-01 的 v0.8.0 就是这么挂的,`deploy_server.sh` 里有记录)。

**自检接口只报"配没配上",不回显任何值** —— 所以它的输出可以贴给我看:

```bash
curl -s https://<你的域名>/admin/readiness -H "Authorization: Bearer <管理员token>" \
  | python3 -m json.tool
```

要看的两行:

- `payment_wechat.configured` 应该变成 `true`;
- `mock_pay_disabled.configured` 必须是 `true`。

**注意**:`wxpay_configured` 要 5 项齐全才为真
(app_id / mchid / api_v3_key / cert_serial_no / private_key_path,
见 `server/app/config.py:283`)。少一项就还是 false。

---

## 五、真金白银验一笔(**要等第六步有了二级商户**)

自检绿了只说明**配置项非空**,不代表验签、回调、金额都对。必须真跑一笔。

⚠️ 收付通下单必传 `sub_mchid`,所以这一步做不了 —— 得先有一个二级商户。
**顺序是:三、四步配好 → 第六步给一家真实商家进件 → 回到这一步验。**
拿你自己或者第一家愿意配合的商家做这个"第一单"。

1. 用户端下一个**最小额**订单(1 分钱最好,商家菜单里临时上一道);
2. 走微信支付付掉;
3. 看订单状态有没有变成「已支付」;
4. 看服务端日志有没有收到回调:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs api --tail 200 | grep -i wechat
```

**三个最常见的坑:**

- **回调进不来。** `WXPAY_NOTIFY_URL` 必须是公网可达的 https,而且
  商户平台里也要配同一个地址。回调进不来的表现是:钱扣了、订单还是待支付;
- **验签失败(400)。** 多半是公钥/平台证书模式搞混了,或者
  `WXPAY_CERT_SERIAL_NO` 填成了平台证书的序列号(要填**商户证书**的);
- **回调 404 是正常的。** 代码里是故意的:回调可能跑在下单事务提交之前,
  返回 404 让微信按 15s/15s/30s… 重试,日志里会写明"已让微信重试"
  (`payments.py:106` 那段注释)。看到一次 404 之后紧跟一次成功,是对的。

---

## 六、之后才是收付通进件与分账(我来写代码)

支付跑通了再做。商家端的资料采集已经做好了
(`apps/merchant_app/lib/applyment_page.dart`,身份证号和银行账户
Fernet 加密落库、接口只回尾号),**提交给微信的那一步还没接**。

类目定了,所以要接的是这三段:

1. **进件** `/v3/ecommerce/applyments/` —— 提交后拿 `applyment_id`,
   轮询状态回填 `merchant.sub_mchid`;
2. **下单带 sub_mchid** `/v3/pay/partner/transactions/app` ——
   注意这是 **partner** 路径,和直连的 `/v3/pay/transactions/app` 不是一个;
3. **分账** `/v3/ecommerce/profitsharing/orders`。

**这三段我都不需要你的密钥** —— 代码从 `.env.prod` 读,我只写代码。

### 收付通特有的三个坑,先写在这

- ⚠️ **`settle_info.profit_sharing=true` 必须在下单时就传。**
  漏传的订单**事后补不了**,只能全额退款重来。分账还有 30 天窗口,
  过期只能退款或转普通结算;
- ⚠️ **二级商户有独立的账户余额。** 收付通的钱先进二级商户的
  「不可用余额」,分账之后才可用。所以商家看到的「可提现」和我们
  自己的台账口径要对齐,不然他会觉得平台扣了他的钱;
- ⚠️ **进件驳回要能改了重提。** 微信驳回时给的是字段级原因,
  商家端现在有 `applyment_reject_reason` 字段但只存一句话 ——
  接的时候要把微信返回的逐字段原因落下来,否则商家只知道"被拒了"
  不知道改哪。

---

## 如果哪一步卡住

把**报错信息和自检接口的输出**贴给我 —— 那些不含密钥。
不要贴 `.env.prod` 的内容、不要贴证书文件、不要截商户平台的密钥页。

我能从报错定位到是哪一环,但我不需要、也不会要那些值。
