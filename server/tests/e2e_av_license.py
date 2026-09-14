"""视听许可证编号的公示:后台「平台开关」里填 → /config 的 licenses.av → 官网页脚、App「关于我们」。

- 填了照原样下发(只清洗成一行、60 字以内,不猜格式);
- 清空就不下发(空串),页脚和「关于我们」不显示那一行;
- 只有管理员能改。

    SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_av_license
"""
from tests.util import ADMIN, call, login


def main() -> None:
    admin = login(ADMIN)
    before = call("GET", "/admin/flags", admin).get("av_license_no", "")
    try:
        call("POST", "/admin/flags/av_license_no", admin,
             {"value": "  测试字第 0001 号\n(e2e)  ", "reason": "e2e 测试"})
        assert call("GET", "/config")["licenses"]["av"] == "测试字第 0001 号 (e2e)"
        assert call("GET", "/admin/flags", admin)["av_license_no"] == "测试字第 0001 号 (e2e)"
        long = "证" * 80
        call("POST", "/admin/flags/av_license_no", admin, {"value": long})
        assert call("GET", "/config")["licenses"]["av"] == "证" * 60
        call("POST", "/admin/flags/av_license_no", admin, {"value": ""})
        assert call("GET", "/config")["licenses"]["av"] == ""
        print("✓ 后台填的编号照原样公示(清洗成一行、60 字以内);清空就不下发")

        customer = login("13800000001")
        r = call("POST", "/admin/flags/av_license_no", customer, {"value": "伪造"}, expect_error=True)
        assert r["_error"] == 403, r
        assert call("GET", "/config")["licenses"]["av"] == ""
        print("✓ 只有管理员能改")
    finally:
        call("POST", "/admin/flags/av_license_no", admin, {"value": before, "reason": "e2e 复原"})
    print("e2e_av_license 全部通过 ✅")


if __name__ == "__main__":
    main()
