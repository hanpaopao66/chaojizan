#!/usr/bin/env python3
"""查「箭头 setState 把 Future 当返回值交出去」。

    setState(() => _future = widget.api.load());   // ← 赋值表达式的值就是那个 Future

setState 的回调返回了 Future,debug 包直接断言失败(「setState() callback argument returned a Future」),
这一轮也不重建;release 包断言被剥掉,碰巧能用 —— 所以真机调试时才炸,测试和线上都看不出来。
下拉刷新里这么写还有第二个问题:onRefresh 不等加载完就返回,转圈一闪就没。

改法:先把 Future 建好,再用块写法赋值:

    final f = widget.api.load();
    setState(() {
      _future = f;
    });
    await f.then((_) {}, onError: (_) {});   // 下拉刷新要等到真拉完

判据(按名字和形状,不做类型推断):箭头 setState 里给名字带 future 的字段赋值,或者赋的是 api 调用的结果。
"""
import os
import re
import sys

ROOTS = ['apps/user_app/lib', 'apps/merchant_app/lib', 'apps/rider_app/lib', 'packages/shared/lib']
PAT = re.compile(
    r'setState\(\s*\(\)\s*=>\s*(?:this\.)?_?\w*[Ff]uture\w*\s*=(?!=)'
    r'|setState\(\s*\(\)\s*=>\s*(?:this\.)?_?\w+\s*=\s*(?:widget\.)?(?:api|_api|store\.api|videoApi|rootApi)\.\w+\(')


def main() -> int:
    hits = []
    for base in ROOTS:
        for root, _, files in os.walk(base):
            for f in files:
                if not f.endswith('.dart'):
                    continue
                p = os.path.join(root, f)
                src = open(p, encoding='utf-8').read()
                lines = src.split('\n')
                # 整个文件一起扫:`setState(\n  () => _future = …)` 这种跨行写法也要抓到
                for m in PAT.finditer(src):
                    i = src.count('\n', 0, m.start()) + 1
                    if lines[i - 1].lstrip().startswith('//'):
                        continue
                    hits.append(f'{p}:{i}: {" ".join(m.group(0).split())[:100]}')
    if hits:
        print('✗ 箭头 setState 把 Future 交给了 setState(debug 包断言失败,改成块写法):')
        for h in hits:
            print('  ' + h)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
