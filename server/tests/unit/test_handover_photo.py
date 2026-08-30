"""发货照:零售商家拣完货必须拍一张(#304)。

## 这组测试守什么

零售的纠纷和外卖不是一类。外卖是"味道不对""洒了",照片帮不上;
零售是**少给了、给错了、坏的** —— 那正是一张照片能定的事。

跑腿那条线早就有同样的东西(`Order.pickup_photo_url`,注释写着
「丢件纠纷时唯一的事实来源」)。零售是同一个道理,只是拍的人和时刻不同。

三件事锁住:

1. **只对零售强制。** 凭空让每个快餐店每天多按几十次快门,换不来什么。
2. **和跑腿的「不强制」是有意相反的决定,不是漏了。** 那边的理由写着
   「骑手在楼道里手忙脚乱,卡住照片就等于卡住取件」;商家发货的处境
   不同(自己柜台前、有平板、每天重复几十遍)。这条测试把两处的差异
   钉成"经过判断的",免得后来的人以为是不一致。
3. **判权要写对。** 私密文件是默认拒绝 + 逐类放行的,漏写一个分支的后果
   不是报错,是**顾客打开纠纷页看到一张破图** —— 而那正是他最需要它的时候。
"""
import inspect

from app.services.storage import PURPOSES


class Test只对零售强制:
    def test_闸按业态判(self):
        from app.routers.orders import transition
        src = inspect.getsource(transition)
        assert 'biz_type == "retail"' in src, "发货照的闸没有按业态分"
        assert "handover_photo_url" in src

    def test_餐饮愿意拍也存着但不拦(self):
        """商家自己想留证的,没理由拒收。"""
        from app.routers.orders import transition
        src = inspect.getsource(transition)
        i = src.index('biz_type == "retail"')
        assert "elif payload.photo_url.strip():" in src[i:], \
            "餐饮传了照片应当存下来,只是不强制"


class Test和跑腿的不强制是有意相反:
    def test_跑腿那条仍然不强制(self):
        """**不是要改它。** 这条在这里,是为了万一有人"统一"两处时,
        测试会告诉他这两个处境本来就不同。"""
        from app.routers.errands import upload_pickup_photo
        doc = inspect.getdoc(upload_pickup_photo) or ""
        assert "不强制" in doc, (
            "跑腿取件照原本明确写着不强制(骑手在楼道里手忙脚乱)。"
            "改它之前先想清楚:商家在柜台前和骑手在楼道里不是一个处境")

    def test_零售这条说清楚了为什么不一样(self):
        from app.routers.orders import transition
        src = inspect.getsource(transition)
        assert "errands.upload_pickup_photo" in src, \
            "强制的这一处要指向不强制的那一处,否则读起来像自相矛盾"


class Test拦住之后订单不能卡死:
    def test_抢单池收accepted和ready两种(self):
        """闸拦住的话订单停在 accepted。骑手照样抢得到、到得了店,
        所以只是商家得把照片补上,**不是整单卡死**。

        这条守的正是那个前提。它和发货照看着无关,但一旦有人把抢单池
        收窄到只收 ready,这个闸就从"慢一步"变成"卡死一单",
        而那时没人会想到是这两件事凑到一起。"""
        from app.models import OrderStatus
        from app.state_machine import GRABBABLE_STATUSES
        assert OrderStatus.ACCEPTED in GRABBABLE_STATUSES, (
            "抢单池不再收 accepted 的话,发货照的闸就会把订单卡死")
        assert OrderStatus.READY in GRABBABLE_STATUSES


class Test判权:
    def test_进私密桶(self):
        """照片会说明这个人买了什么 —— 买药、买成人用品都在这一类里。"""
        assert PURPOSES["handover_proof"] is True

    def test_三方各有一条放行且骑手只在途(self):
        from app.routers.uploads import _may_read_private
        src = inspect.getsource(_may_read_private)
        i = src.index("handover_photo_url")
        seg = src[i:i + 700]
        assert "Order.customer_id == user.id" in seg, "顾客看不到 = 纠纷时他空口说"
        assert "Merchant.owner_id == user.id" in seg, "商家看不到自己拍的"
        assert "Order.rider_id == user.id" in seg
        assert "COMPLETED" in seg and "CANCELLED" in seg, (
            "骑手要限制在途 —— 送完就没有继续看的理由,"
            "而照片说明这个人买了什么")

    def test_不在上传者例外名单里(self):
        """`_NOT_SELF_PURPOSES` 是给"拍的是别人的东西"准备的
        (送达留证拍的是别人家门口)。发货照拍的是商家自己柜台上的货,
        他本来就该一直看得到。"""
        from app.routers.uploads import _NOT_SELF_PURPOSES
        assert "handover_proof" not in _NOT_SELF_PURPOSES
