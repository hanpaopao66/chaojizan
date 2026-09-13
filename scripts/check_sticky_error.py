#!/usr/bin/env python3
"""查「出错页点重试、下拉,拉成功了也回不来」。

    body: _error != null
        ? SzError(error: _error, onRetry: _load)       // ← 出错页排在数据前面判断
        : _data == null ? const Center(child: CircularProgressIndicator()) : _content(),

    Future<void> _load() async {
      try {
        final d = await widget.api.load();
        if (mounted) setState(() => _data = d);         // ← 拉成功了没把 _error 清掉
      } catch (e) {
        if (mounted) setState(() => _error = '$e');
      }
    }

断一次网,这一页就一直挂在出错页上:点「重试」、下拉都只是在后台把数据拉回来了,界面纹丝不动,
看着像按钮坏了。不报错,测试不专门测也看不出来。

判据:`body:` / `child:` / `return` 后面紧跟着 `_error != null ?`(或 `_error.isNotEmpty ?`),
而同一个类里没有一处把这个字段清掉(`_error = null` / `_error = ''` / `_error = … : null`)。
外面已经判过数据为空的不算(`if (_data == null) { … }`、`_data == null ? … : …` 里面):拉成功之后走的是另一个分支。
确实不需要的地方在那一行写 `// sticky-error: ok 原因`。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_refresh_pullable import ROOTS, Source  # noqa: E402  同一套 Dart 括号配对

FIRST = re.compile(r'(?:\bbody|\bchild|\breturn)\s*:?\s*(_\w*[eE]rr\w*)\s*(?:!=\s*null|\.isNotEmpty)\s*\?')
CLASS = re.compile(r'\bclass\s+\w+[^{;]*\{')
OK_MARK = 'sticky-error: ok'


def _guarded(sf, pos, stop):
    """pos 外面是不是已经判过「数据为空」:`if (x == null) { … }`、`if (x == null) Widget(…)`、
    `x == null ? Widget(…) : …` 这三种。一路往外看包住它的括号,看到类的大括号为止。"""
    src = sf.text
    for o in sorted((o for o, c in sf.pairs.items() if stop < o < pos < c), reverse=True):
        j = o
        if src[o] == '(':
            # 跳过被调用的 widget 名(`const Center(` 的 `const Center`)
            k = o - 1
            while k > 0 and (src[k].isalnum() or src[k] in '_$.<> ' or src[k] == '\n'):
                k -= 1
            j = k + 1
        before = src[max(0, j - 160):j].rstrip()
        if re.search(r'==\s*null\s*\)$', before) or re.search(r'==\s*null\s*\?$', before):
            return True
    return False


def scan_source(sf):
    hits = []
    src = sf.text
    classes = [(m.end() - 1, sf.pairs.get(m.end() - 1, len(src))) for m in CLASS.finditer(src)]
    for m in FIRST.finditer(src):
        line_no = sf.line_of(m.start())
        if OK_MARK in sf.lines[line_no - 1]:
            continue
        owner = [(a, b) for a, b in classes if a < m.start() < b]
        if not owner:
            continue
        a, b = max(owner)  # 最里面的那个类
        if _guarded(sf, m.start(), a):  # 外面已经判过「数据为空」:拉成功之后不会再走到这里
            continue
        name = re.escape(m.group(1))
        body = src[a:b]
        cleared = (re.search(r'(?<![\w.])' + name + r'\s*=\s*(?:null|\'\'|"")\s*[;,)]', body)
                   or re.search(r'(?<![\w.])' + name + r'\s*=[^;]*:\s*(?:null|\'\'|"")\s*;', body))
        if not cleared:
            hits.append(f'{sf.path}:{line_no}: 出错页排在最前面,但拉成功时从来不清 {m.group(1)}')
    return hits


def main() -> int:
    hits = []
    for base in ROOTS:
        for root, _, files in os.walk(base):
            for f in files:
                if f.endswith('.dart'):
                    p = os.path.join(root, f)
                    hits += scan_source(Source(p, open(p, encoding='utf-8').read()))
    if hits:
        print('✗ 出错页点重试、下拉,拉成功了也回不来(拉成功时把错误清掉):')
        for h in hits:
            print('  ' + h)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
