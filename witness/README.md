# Super-Z 社区见证节点

**用一台旧电脑,监督一个平台不作恶。**

Super-Z 承诺:商家佣金只收 5%、配送费 100% 归骑手、账目三方透明。
承诺不该靠平台自觉,该靠数学和你——平台每天把全部账务流水(匿名化,
无任何个人信息)按哈希链公开,你的节点独立复算、留存、示警。

## 它如何让平台无法作假

1. **哈希链**:每天的账本生成 `chain_hash = sha256(昨日链哈希 + 今日账本哈希)`。
   改历史上任何一分钱,之后所有天的哈希全部对不上。
2. **分布式留存**:你的节点把见过的锚点存在你自己的机器上
   (`/data/witness.json`)。平台若改写或删除历史锚点,你的节点在
   5 分钟内发现,并在 [平台节点页](https://aikas.com.cn/nodes) 公开示警。
3. **逐行核账**:节点重算每一行流水——佣金是否 ≤ 承诺上限(当前 5%,费率内嵌在每日账本里,历史锚点按当天口径复算)、净额恒等式、
   配送费是否只进不冲、团购服务费是否恰好等于承诺费率(当前 2%)。

节点越多,篡改越不可能。这就是我们说"账目透明"时的全部含义。

## 运行(任选其一,门槛从低到高)

**绿色版(推荐给普通用户):下载、双击、完事**

[Windows](https://aikas.com.cn/appdist/witness/superz-witness-windows.exe) ·
[macOS](https://aikas.com.cn/appdist/witness/superz-witness-macos.zip) ·
[Ubuntu/Linux](https://aikas.com.cn/appdist/witness/superz-witness-linux.tar.gz)
(亦可从 GitHub Release 下载)

单文件约 6MB,零依赖零安装:双击出现小窗口,每 5 分钟自动核账一轮;
状态存在程序旁边的 witness-state.json,删掉两个文件即彻底卸载。
macOS 首次打开用右键→打开(程序未做付费签名)。
源码在 witness/go/(Go,单文件),构建:scripts/build_witness_dist.sh。


**Docker(推荐)**

```bash
docker build -t superz-witness .
docker run -d --name superz-witness --restart unless-stopped \
  -v superz-witness-data:/data \
  -e WITNESS_NAME=老王 -e WITNESS_REGION=成都 \
  superz-witness
```

**直接跑(只需要 Python 3.10+,零第三方依赖)**

```bash
python3 superz_witness.py
```

`WITNESS_NAME` / `WITNESS_REGION` 自愿填写,只用于节点页展示;
不填就匿名。节点不收集、不上传关于你的任何信息——上报内容只有:
自生成的随机节点 ID、校验到哪天、链哈希、校验结论。源码不到 300 行,
建议读一遍再运行:见证的意义在于不需要信任任何人,包括我们。

## 诚实声明

- 见证节点**不参与业务运行**。订单、支付、个人数据在平台法人主体的
  服务器上处理并担责——这是法律要求,也是外卖这种物理世界服务的必然。
- 节点数量是**社会证明,不是共识机制**。刷节点数骗不到任何回报
  (节点没有、也永远不会有金钱回报),只会多几台机器帮我们核账。
- 节点网络 + AGPL 开源 + 公开财报,共同保证的是**可重建性**:
  即使官方服务器消失,任何人手里都有完整的重建图纸与账目存证。
