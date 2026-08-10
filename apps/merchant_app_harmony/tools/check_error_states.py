"""查「空列表和加载失败长得一样」。

这是商家端最危险的歧义,也是这个仓库反复出现的一类 bug:

- 评价拉不到显示「这一栏没有评价」→ 差评看不到,错过申诉窗口;
- 菜单拉不到显示「还没有菜品」→ 商家跑去重录一遍;
- 店员名单拉不到显示空列表 → 店主以为清光了,而那些账号还在听单;
- 云打印配置拉不到显示「平台还未开通」→ 商家据此就不去绑打印机。

安卓端为此改过一整批(DEV-PROMPTS-27 #240)。这个脚本让同类问题
在鸿蒙端能被机器查出来,而不是靠下一次 review 撞见。

判据:一个页面只要**调了接口**,就必须**同时**有

  1. 错误态字段(errorText / xxxError),且
  2. 一条重试路径(按钮或可点横幅)。

有意静默的(次要数据兜底)要在 catch 里写注释说明为什么 ——
脚本不检查注释内容,但空 catch 会被单独列出来。

    python3 tools/check_error_states.py .
"""
import re
import sys
import pathlib

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
pages = sorted((root / 'entry/src/main/ets/pages').rglob('*.ets'))

problems = []
for p in pages:
    s = p.read_text()
    name = p.name

    # 判据只对**进页面就自动拉数据**的页生效。
    #
    # 用户点按钮才发请求的页(登录、订单详情的接单/打印、店铺的开关)
    # 不适用:那里的"重试"就是再点一次按钮,失败用 toast 说清楚就够了。
    # 对它们也报错的话,这个脚本就会开始报假警 —— 而报假警的检查器
    # 迟早被人忽略,那比没有更糟。
    appear = re.search(r'aboutToAppear\s*\([^)]*\)[^{]*\{(.*?)\n  \}',
                       s, re.S)
    auto_loads = bool(appear and re.search(
        r'this\.(load|reload|refresh)\(|this\.api\.', appear.group(1)))

    if auto_loads:
        has_error_state = bool(
            re.search(r'@State\s+private\s+\w*[Ee]rror\w*\s*:', s))
        has_retry = '重试' in s
        if not has_error_state:
            problems.append(f"{name}: 进页面就拉数据,却没有错误态字段 —— "
                            "失败时会停在转圈或空列表上")
        if not has_retry:
            problems.append(f"{name}: 进页面就拉数据,却没有重试入口 —— "
                            "商家遇到失败只能杀进程重开")

    # 所有页都查:有意静默也要写清为什么
    for m in re.finditer(r'catch\s*\(\s*_?\w*\s*\)\s*\{([^{}]*)\}', s):
        if m.group(1).strip() == '':
            line = s[:m.start()].count('\n') + 1
            problems.append(f"{name}:{line} 空 catch,连注释都没有 —— "
                            "有意静默也要写清为什么")

print(f"扫了 {len(pages)} 个页面")
if problems:
    for x in problems:
        print("  ★", x)
    print(f"\n共 {len(problems)} 处")
    sys.exit(1)
print("错误态与重试路径齐全")
