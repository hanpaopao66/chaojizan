#!/usr/bin/env python3
"""查「弹层里的输入框控制器在 await 弹层回来之后马上销毁」这种写法。

    final c = TextEditingController();
    final r = await showDialog(... TextField(controller: c) ...);
    c.dispose();                      // ← 不行

pop 那一刻 future 就回来了,弹层还在退场动画里、输入框还挂着;手机上键盘同时在收,
弹层跟着重建,输入框重建时用到已经销毁的控制器 —— debug 包整屏红(安卓走查 #376 发评论时撞到),
release 包是在用一个销毁了的对象。网页上没有软键盘收起这一步,测不出来。

改法:弹层内容包一层 `SzDisposeWith(controllers: [c], child: ...)`(packages/shared),不再手动 dispose。
try/finally 里 dispose、`.whenComplete(c.dispose)` 是同一回事,一样拦。
"""
import os
import re
import sys

ROOTS = ['apps/user_app/lib', 'apps/merchant_app/lib', 'apps/rider_app/lib', 'packages/shared/lib']
SHOW = re.compile(r'\b(showDialog|szShowSheet|showModalBottomSheet|showCupertinoDialog|showGeneralDialog)\b')
LOCAL = re.compile(r'^\s*final (\w+) = (TextEditingController|FocusNode)\(')


def scan(path: str) -> list[str]:
    lines = open(path, encoding='utf-8').read().split('\n')
    out = []
    for i, line in enumerate(lines):
        m = LOCAL.match(line)
        if not m:
            continue
        name = m.group(1)
        shown = False
        for j in range(i + 1, min(len(lines), i + 150)):
            s = lines[j]
            if SHOW.search(s):
                shown = True
            if re.search(rf'whenComplete\(\s*{name}\.dispose\s*\)', s):
                out.append(f'{path}:{j + 1}: {name} 在弹层的 future 完成时销毁(whenComplete)')
                break
            if shown and re.search(rf'\b{name}\.dispose\(\)', s):
                out.append(f'{path}:{j + 1}: {name} 在 await 弹层之后马上销毁')
                break
            # 到了下一个顶层 / 类成员声明就不再往下看
            if j > i + 1 and re.match(r'^(  )?(Future|void|Widget|class|@override|[A-Z]\w*<?[\w<>?, ]*>? \w+\()', s):
                break
    return out


def main() -> int:
    hits = []
    for base in ROOTS:
        for root, _, files in os.walk(base):
            for f in files:
                if f.endswith('.dart'):
                    hits += scan(os.path.join(root, f))
    if hits:
        print('✗ 弹层里的控制器在弹层退场之前就销毁了(改用 SzDisposeWith):')
        for h in hits:
            print('  ' + h)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
