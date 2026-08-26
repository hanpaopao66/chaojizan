"""收款户名归一化:该抹的抹掉,不该模糊的一个都不模糊。

## 这组测试守什么

「实名张三、提现打给李四」是账号出租最硬的信号 —— 它在资金侧,比轨迹、
比设备指纹都难伪造:租号的人图的就是把钱收走。众包没有站长天天见人,
这条检查是顶替跑单为数不多能查的东西,而且不需要人脸。

比对的分寸是这条检查的全部:

- **松一点点**:空白和间隔号要抹掉。少数民族姓名里的「·」在身份证、
  银行系统、手机输入法里常常是不同码位,不统一就会把
  「买买提·艾力」判成两个人 —— 而这恰恰是最不该被误伤的一批人;
- **不能再松**:同音字、简繁、姓名顺序一律不碰。模糊到能把"不是同一个
  人"判成同一个人,这条检查就没有存在意义了。
"""
import pytest

from app.routers.payout import normalize_holder_name as norm


class Test该抹掉的:
    @pytest.mark.parametrize("holder,real", [
        ("张三", "张三"),
        ("张 三", "张三"),            # 半角空格
        ("张　三", "张三"),       # 全角空格
        ("张 三", "张三"),       # 不换行空格(从网页复制常带)
        (" 张三 ", "张三"),           # 首尾空白
        ("张\t三", "张三"),
    ])
    def test_空白不影响判定(self, holder, real):
        assert norm(holder) == norm(real)

    @pytest.mark.parametrize("sep", [
        "·",   # · MIDDLE DOT,身份证上最常见
        "‧",   # ‧ HYPHENATION POINT
        "•",   # • BULLET
        "・",   # ・ KATAKANA MIDDLE DOT,某些输入法出这个
        "･",   # ･ HALFWIDTH KATAKANA MIDDLE DOT
    ])
    def test_各种间隔号都算同一个人(self, sep):
        """少数民族姓名的间隔号码位不统一 —— 这批人最不该被误伤。"""
        assert norm(f"买买提{sep}艾力") == norm("买买提·艾力")

    def test_间隔号加空格的混写也认(self):
        assert norm("买买提 · 艾力") == norm("买买提·艾力")


class Test不该模糊的:
    @pytest.mark.parametrize("holder,real", [
        ("李四", "张三"),        # 完全不同的人
        ("张三丰", "张三"),      # 多一个字不是同一个人
        ("张三", "张三丰"),
        ("三张", "张三"),        # 顺序不同不算同一个人
        ("章三", "张三"),        # 同音字**不能**放过
        ("張三", "张三"),        # 简繁**不能**放过:银行户名以证件为准
    ])
    def test_这些必须判成不一致(self, holder, real):
        assert norm(holder) != norm(real), (
            f"「{holder}」被判成了「{real}」—— 松到这个程度,"
            f"这条检查就拦不住冒用了")


class Test边界:
    def test_空串不炸(self):
        assert norm("") == ""
        assert norm(None) == ""

    def test_全是空白归一化成空串(self):
        assert norm("  　 ") == ""
