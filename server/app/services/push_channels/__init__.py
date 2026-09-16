"""推送通道:一条通道一个模块,上面由 services/push.py 按设备选路(#384)。

每条通道长成同一个样子(见 base.py):`configured()` 和 `send(...) -> Result`,
所以选路那圈循环不认识任何一家具体是谁 —— **加一家只加一行映射**。

已经接好的:

- `apns`   苹果。直连,免费无配额,认证是一个 .p8 密钥;
- `hms`    华为。先换 access_token 再发,业务码在响应体里(不是 HTTP 状态码);
- `xiaomi` 小米。请求头直接带 AppSecret,不用换令牌,收的是表单;
- `oppo`   OPPO。先换 auth_token;签名 SHA256,时间戳**毫秒**;
- `vivo`   vivo。先换 authToken;签名 **MD5**(和 OPPO 不一样),消息类别要按后台申请的填。

还没接的:荣耀(honor)。通道名在 push_devices.CHANNELS 里占着位,
这类设备登记进来发不出去,**push_logs 里会写明「这条通道还没接」** ——
不静默跳过,"推送没到"这件事没人会来报 bug,只能靠日志自己看得见。

**每配好一家都要用 `python -m scripts.push_probe` 实发一条验一次。**
各家的接口只回一句笼统的错误(签名算错、时间戳单位错、类别标错都回"鉴权失败"),
不实发根本看不出来配没配对。
"""
