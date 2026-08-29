# 超级赞 MCP 服务

让 AI 助手（Claude、以及任何支持 MCP 的客户端）帮你找店、比价、下单、查进度。

## 它做不到什么（先说这个）

**它付不了款。** 助手能把单创建到「待支付」为止，付款那一下在你自己的
App 里，由你按。所以即使这个令牌泄露，对方能替你创建一张 15 分钟后
自动关闭的待付单，**但花不掉你一分钱**。

同样做不到的还有：退款、改地址、动地址簿、提申诉、钱包与提现。

这是有意的设计，不是没做完 —— 判断权留给人。

## 怎么接

1. 在超级赞 App 里：我的 → 设置 → AI 助手，签发一个令牌（**明文只显示一次**）
2. 把下面这段加进你的 MCP 客户端配置：

```json
{
  "mcpServers": {
    "superz": {
      "command": "python3",
      "args": ["/绝对路径/mcp-server/server.py"],
      "env": {
        "SUPERZ_API": "https://你的域名",
        "SUPERZ_AGENT_TOKEN": "刚才复制的那串"
      }
    }
  }
}
```

3. 不放心就先干跑一次：

```bash
SUPERZ_API=https://你的域名 SUPERZ_AGENT_TOKEN=xxx python3 mcp-server/server.py --selftest
```

## 没有沙箱，这一点要说清楚

**现在没有独立的沙箱环境。** 你在生产环境试 `create_pending_order`
会产生**真实的待支付订单** —— 不付款的话 15 分钟后自动关闭，不会扣钱，
但商家端会看到这张单闪一下。

不做沙箱是权衡的结果：独立沙箱库要维护一套数据，生产库打标一旦漏判
就是真钱。而因为没有支付工具，试用的风险已经被压得很低。

## 工具

| 工具 | 做什么 |
|---|---|
| `search_merchants` | 按位置和关键词找店 |
| `get_menu` | 看菜单、规格、库存 |
| `quote_order` | **算价不下单**：配送费明细、预计送达 |
| `create_pending_order` | 创建待支付订单，返回订单号让你去 App 里确认 |
| `get_order_status` | 这单到哪一步了 |
| `list_my_orders` | 我的订单 |
| `get_transparency` | 平台的公开口径（判责、派单、排队规则） |

`quote_order` 单独拆出来是有意的：助手最常做的事是比价，
让它能算价而不产生垃圾订单。

## 没有依赖

只用 Python 标准库。这是开源项目，少一个依赖少一份供应链风险，
而一个最小的 JSON-RPC over stdio 实现只有几百行。
