#!/usr/bin/env python3
"""查「下拉刷新拉不动」:列表空着、或者内容不满一屏时,往下拉没反应(不报错,就是拉不出圈)。

RefreshIndicator 靠它下面最近那一层滚动视图的越界通知工作。三种写法会让它静默失效:

1. 空状态没包进下拉刷新(最常见):

       body: items.isEmpty
           ? const SzEmpty(text: '还没有')              // ← 空着的时候拉不动,新数据进来只能退出重进
           : RefreshIndicator(onRefresh: _load, child: ListView(...)),

   三元的每一支、同一个函数里的每个 return、同一个变量的每次赋值都算。
   改法:空状态换成 `SzRefreshableEmpty(onRefresh: _load, child: SzEmpty(...))`。

2. 包进去了,但那个分支里没有能滚的东西:

       RefreshIndicator(onRefresh: _load, child: rows.isEmpty ? const SzEmpty(...) : ListView(...))

   改法:空状态也放进 `ListView(children: [...])`。

3. 滚动视图不满一屏时不接受拖动:Flutter 只在「竖向、没传 controller、没写 primary」时
   默认给 AlwaysScrollableScrollPhysics(写死在 ScrollView 的构造函数里)。传了 controller、
   写了 primary 的 ListView / GridView / CustomScrollView,还有 SingleChildScrollView(它没有这个默认),
   不写 physics 就用平台默认,内容不满一屏时拖不动。改法:`physics: const AlwaysScrollableScrollPhysics()`。
   没传 controller 的普通 ListView 本来就拉得动,不用补 physics。

只转圈 / 骨架屏的加载分支不算;出错页(名字带 Error,或者有「重试」按钮)有别的路回来,也不算。
确实不需要的地方,在报出来的那一行或者 RefreshIndicator 那一行写 `// refresh-pullable: ok 原因`。
"""
import os
import re
import sys

ROOTS = ['apps/user_app/lib', 'apps/merchant_app/lib', 'apps/rider_app/lib', 'packages/shared/lib']
OK_MARK = 'refresh-pullable: ok'
REFRESH = re.compile(r'\bRefreshIndicator(?:\.adaptive)?\(')
SCROLL_NAMES = {
    'ListView', 'ListView.builder', 'ListView.separated', 'ListView.custom',
    'GridView', 'GridView.builder', 'GridView.count', 'GridView.extent', 'GridView.custom',
    'CustomScrollView', 'SingleChildScrollView', 'ReorderableListView', 'ReorderableListView.builder',
    'PageView', 'PageView.builder', 'PageView.custom',
}
UNJUDGED = {'NestedScrollView'}  # 自己协调里外两层滚动,不在这里判
LOADING = re.compile(r'ProgressIndicator|Skeleton|Shimmer|Loading')
PLACEHOLDER = {'SizedBox', 'SizedBox.shrink', 'SizedBox.expand', 'Container', 'Placeholder', 'Offstage'}
CONTROL = {'if', 'for', 'while', 'switch', 'catch'}
IDENT = re.compile(r'[A-Za-z0-9_$]')

OK, BAD, NONE, LOAD, UNKNOWN = 'ok', 'bad', 'none', 'loading', 'unknown'
ERR = 'error'          # 出错态:有「重试」按钮,拉不拉得动不强求
REFRESHED = 'refresh'  # 这个分支本身就是一个 RefreshIndicator(找它的兄弟分支时用)


class Result:
    def __init__(self, status, sf=None, pos=0, msg=''):
        self.status, self.sf, self.pos, self.msg = status, sf, pos, msg


class Source:
    def __init__(self, path, text):
        self.path, self.text = path, text
        self.lines = text.split('\n')
        self.pairs = _pairs(text)

    def line_of(self, pos):
        return self.text.count('\n', 0, pos) + 1


# ---------- 词法:跳过字符串和注释,括号配对 ----------

def _skip_string(src, i):
    q = src[i]
    raw = i > 0 and src[i - 1] == 'r' and (i < 2 or not IDENT.match(src[i - 2]))
    if src[i:i + 3] == q * 3:
        j = src.find(q * 3, i + 3)
        return len(src) if j < 0 else j + 3
    i += 1
    while i < len(src) and src[i] != q:
        if src[i] == '\\' and not raw:
            i += 2
            continue
        if src[i] == '$' and not raw and src[i + 1:i + 2] == '{':
            depth, i = 1, i + 2
            while i < len(src) and depth:
                if src[i] in '\'"':
                    i = _skip_string(src, i)
                    continue
                depth += {'{': 1, '}': -1}.get(src[i], 0)
                i += 1
            continue
        if src[i] == '\n':
            return i
        i += 1
    return i + 1


def _skip(src, i):
    """i 指着字符串或注释的开头时,返回它结束之后的下标;否则原样返回 i。"""
    if src.startswith('//', i):
        j = src.find('\n', i)
        return len(src) if j < 0 else j
    if src.startswith('/*', i):
        j = src.find('*/', i + 2)
        return len(src) if j < 0 else j + 2
    if src[i] in '\'"':
        return _skip_string(src, i)
    return i


def _pairs(src):
    pairs, stack, i = {}, [], 0
    while i < len(src):
        j = _skip(src, i)
        if j != i:
            i = j
            continue
        ch = src[i]
        if ch in '([{':
            stack.append(i)
        elif ch in ')]}' and stack:
            o = stack.pop()
            pairs[o], pairs[i] = i, o
        i += 1
    return pairs


def _ws(src, i, e):
    """跳过空白和注释。"""
    while i < e:
        if src[i].isspace():
            i += 1
        elif src.startswith('//', i) or src.startswith('/*', i):
            i = _skip(src, i)
        else:
            break
    return i


def _trim(sf, s, e):
    src = sf.text
    s = _ws(src, s, e)
    while e > s and src[e - 1].isspace():
        e -= 1
    for kw in ('const ', 'new ', 'await '):
        if src.startswith(kw, s):
            s = _ws(src, s + len(kw), e)
    return s, e


def _generic_end(src, i, e):
    """i 指着类型名后面的 '<'(`Map<String, dynamic>`),返回配对的 '>' 之后的下标;看着不像类型参数就返回 None。"""
    k = i - 1
    while k >= 0 and IDENT.match(src[k]):
        k -= 1
    if k + 1 == i or not src[k + 1].isupper():
        return None
    depth = 0
    for j in range(i, e):
        ch = src[j]
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
            if depth == 0:
                return j + 1
        elif not (ch.isalnum() or ch in '_$ \n\t,.?()'):
            return None
    return None


def _top(sf, s, e):
    """逐个产出 [s, e) 里括号深度为 0 的下标(跳过字符串、注释、整对括号和类型参数)。"""
    src, i = sf.text, s
    while i < e:
        j = _skip(src, i)
        if j != i:
            i = j
            continue
        if src[i] in '([{' and i in sf.pairs:
            yield i
            i = sf.pairs[i] + 1
            continue
        if src[i] == '<':
            j = _generic_end(src, i, e)
            if j:
                i = j
                continue
        yield i
        i += 1


def _split(sf, s, e, sep=','):
    out, start = [], s
    for i in _top(sf, s, e):
        if sf.text[i] == sep:
            out.append((start, i))
            start = i + 1
    out.append((start, e))
    return [(a, b) for a, b in (_trim(sf, a, b) for a, b in out) if a < b]


def _named(sf, open_at, name):
    """call 的参数表里 `name:` 的值的范围。"""
    close = sf.pairs.get(open_at, open_at)
    for a, b in _split(sf, open_at + 1, close):
        m = re.match(r'(\w+)\s*:(?!:)', sf.text[a:b])
        if m and m.group(1) == name:
            return _trim(sf, a + m.end(), b)
    return None


def _ternary(sf, s, e):
    """顶层三元 `c ? x : y` → (x 的范围, y 的范围)。"""
    src, q, nest = sf.text, None, 0
    for i in _top(sf, s, e):
        ch = src[i]
        if ch == '?':
            nxt = src[i + 1:i + 2]
            if nxt in ('.', '?', '[') or src[i - 1] == '?':
                continue
            if q is None:
                q = i
            else:
                nest += 1
        elif ch == ':' and q is not None:
            if nest:
                nest -= 1
                continue
            return _trim(sf, q + 1, i), _trim(sf, i + 1, e)
    return None


def _call(sf, s, e):
    """[s, e) 整个是一次调用 `Name(…)` / `Name.named(…)` / `Name<T>(…)` → (名字, 左括号下标)。"""
    m = re.match(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?', sf.text[s:e])
    if not m:
        return None
    o = _ws(sf.text, s + m.end(), e)
    if sf.text[o:o + 1] == '<':
        o = _ws(sf.text, _generic_end(sf.text, o, e) or o, e)
    if sf.text[o:o + 1] != '(':
        return None
    if sf.pairs.get(o, -1) != e - 1:
        return None
    return m.group(0), o


def _stmt_end(sf, s, limit):
    for i in _top(sf, s, limit):
        if sf.text[i] == ';':
            return i
    return limit


# ---------- 函数体里 return 出去的表达式 ----------

def _is_fn_body(sf, brace):
    src, i = sf.text, brace - 1
    while i >= 0 and src[i].isspace():
        i -= 1
    for kw in ('async*', 'sync*', 'async'):
        if src[i - len(kw) + 1:i + 1] == kw:
            i -= len(kw)
            while i >= 0 and src[i].isspace():
                i -= 1
            break
    if src[i] != ')':
        return False
    o = sf.pairs.get(i)
    if o is None:
        return False
    j = o - 1
    while j >= 0 and src[j].isspace():
        j -= 1
    k = j
    while k >= 0 and IDENT.match(src[k]):
        k -= 1
    return src[k + 1:j + 1] not in CONTROL


def _block_returns(sf, brace):
    src, close, out = sf.text, sf.pairs.get(brace, brace), []
    i = brace + 1
    while i < close:
        j = _skip(src, i)
        if j != i:
            i = j
            continue
        if src[i] == '{' and _is_fn_body(sf, i):
            i = sf.pairs.get(i, i) + 1  # 里面套的闭包 / 局部函数不算
            continue
        if src.startswith('return', i) and not IDENT.match(src[i - 1]) and not IDENT.match(src[i + 6]):
            end = _stmt_end(sf, i + 6, close)
            s, e = _trim(sf, i + 6, end)
            if s < e:
                out.append((s, e))
            i = end + 1
            continue
        i += 1
    return out


def _fn_returns(sf, s, e):
    """[s, e) 是函数字面量 `(…) => expr` 或 `(…) { … }`。"""
    src = sf.text
    if src[s] != '(' or s not in sf.pairs:
        return None
    i = _ws(src, sf.pairs[s] + 1, e)
    if src.startswith('async', i):
        i = _ws(src, i + 5, e)
    if src.startswith('=>', i):
        return [_trim(sf, i + 2, e)]
    if src[i] == '{':
        return _block_returns(sf, i)
    return None


def _decl_returns(sf, name):
    """同一个文件里 `Widget name(…) {…}` / `=> …;` / `Widget get name …` 返回的表达式。"""
    pat = re.compile(r'\b[A-Z]\w*(?:<[\w<>, ?]*>)?\??\s+(get\s+)?' + re.escape(name) + r'\s*([({]|=>)')
    for m in pat.finditer(sf.text):
        i = m.end() - len(m.group(2))
        src = sf.text
        if m.group(2) == '(':
            if m.group(1) or i not in sf.pairs:
                continue
            i = _ws(src, sf.pairs[i] + 1, len(src))
            if src.startswith('async', i):
                i = _ws(src, i + 5, len(src))
        if src.startswith('=>', i):
            end = _stmt_end(sf, i + 2, len(src))
            return [_trim(sf, i + 2, end)]
        if src[i] == '{':
            return _block_returns(sf, i)
    return None


def _member_span(sf, pos):
    """pos 所在的类成员(方法)/ 顶层声明的大致范围:按顶格和两格缩进的声明来切。"""
    starts = [m.start() for m in re.finditer(r'\n(?:  )?[A-Za-z@_]', sf.text)]
    a = max([x for x in starts if x < pos], default=0)
    b = min([x for x in starts if x > pos], default=len(sf.text))
    return a, b


def _assigns(sf, name, a, b):
    """[a, b) 里 `name = …` 的每一次赋值。"""
    out = []
    for m in re.finditer(r'(?<![\w.$])' + re.escape(name) + r'\s*=(?![=>])', sf.text[a:b]):
        v = a + m.end()
        out.append(_trim(sf, v, _stmt_end(sf, v, b)))
    return out


# ---------- 找一个表达式能到达的滚动视图 ----------

def _root_of(path):
    return next((r for r in ROOTS if path.startswith(r)), '')


class Index:
    def __init__(self, sources):
        self.by_file, self.by_root, self.state_of = {}, {}, {}
        for sf in sources:
            mine = self.by_file.setdefault(sf.path, {})
            public = self.by_root.setdefault(_root_of(sf.path), {})
            for m in re.finditer(r'\bclass\s+(\w+)(?:<[^{]*?>)?\s+extends\s+(\w+)(?:\s*<\s*(\w+)\s*>)?[^{]*\{', sf.text):
                mine[m.group(1)] = (sf, m.end() - 1)
                if not m.group(1).startswith('_'):
                    public[m.group(1)] = (sf, m.end() - 1)
                if m.group(2) == 'State' and m.group(3):
                    self.state_of[(sf.path, m.group(3))] = m.group(1)

    def find(self, name, from_sf):
        if name in self.by_file.get(from_sf.path, {}):
            return self.by_file[from_sf.path][name]
        if name.startswith('_'):
            return None
        for root in (_root_of(from_sf.path), 'packages/shared/lib'):
            if name in self.by_root.get(root, {}):
                return self.by_root[root][name]
        return None

    def build_returns(self, name, from_sf):
        hit = self.find(name, from_sf)
        if not hit:
            return None, None
        sf = hit[0]
        for cname in (name, self.state_of.get((sf.path, name))):
            if not cname or cname not in self.by_file[sf.path]:
                continue
            brace = self.by_file[sf.path][cname][1]
            close = sf.pairs.get(brace, len(sf.text))
            m = re.compile(r'\bWidget\s+build\s*\(').search(sf.text, brace, close)
            if not m:
                continue
            o = m.end() - 1
            i = _ws(sf.text, sf.pairs[o] + 1, close)
            if sf.text.startswith('=>', i):
                end = _stmt_end(sf, i + 2, close)
                return sf, [_trim(sf, i + 2, end)]
            if sf.text[i] == '{':
                return sf, _block_returns(sf, i)
        return None, None


def _physics(sf, name, o):
    # 只看这一层自己的参数:列表项里套的横向列表不算
    d = _named(sf, o, 'scrollDirection')
    direction = sf.text[d[0]:d[1]] if d else ('Axis.horizontal' if name.startswith('PageView') else 'Axis.vertical')
    if direction == 'Axis.horizontal':
        return BAD, f'{name} 是横向的,下拉刷新只认竖向'
    phys = _named(sf, o, 'physics')
    if phys:
        text = sf.text[phys[0]:phys[1]]
        if 'AlwaysScrollable' in text:
            return OK, ''
        if re.search(r'(Clamping|Bouncing|NeverScrollable|Page|FixedExtent|RangeMaintaining)ScrollPhysics\(', text):
            return BAD, f'{name} 的 physics 不是 AlwaysScrollable,不满一屏拖不动'
        return OK, ''
    if name == 'SingleChildScrollView':
        return BAD, 'SingleChildScrollView 没有默认的 AlwaysScrollable,不写 physics 不满一屏拖不动'
    prim = _named(sf, o, 'primary')
    if prim:
        if sf.text[prim[0]:prim[1]] == 'true':
            return OK, ''
        return BAD, f'{name} 写了 primary 又没写 physics(primary 为 false 时不满一屏拖不动)'
    ctrl = _named(sf, o, 'scrollController' if name.startswith('Reorderable') else 'controller')
    if ctrl and sf.text[ctrl[0]:ctrl[1]] != 'null':
        return BAD, f'{name} 传了 controller 又没写 physics,不满一屏拖不动'
    return OK, ''


def _list_elements(sf, s, e):
    """列表字面量 [s, e) 里的元素;`if (…) a else b` 拆成两个候选,`for (…) x` 取 x。"""
    out = []
    src = sf.text
    for a, b in _split(sf, s + 1, e - 1):
        while True:
            m = re.match(r'(if|for)\s*\(', src[a:b])
            if not m:
                break
            o = a + m.end() - 1
            a = _ws(src, sf.pairs.get(o, o) + 1, b)
            if m.group(1) == 'if':
                parts = [p for p in _top(sf, a, b) if src.startswith('else', p) and not IDENT.match(src[p - 1])
                         and not IDENT.match(src[p + 4])]
                if parts:
                    out.append(_trim(sf, a, parts[0]))
                    a = _ws(src, parts[0] + 4, b)
        if src.startswith('...', a):
            a = _ws(src, a + 3 + (src[a + 3] == '?'), b)
            if src[a] == '[':
                out += _list_elements(sf, a, b)
                continue
            out.append(None)
            continue
        out.append((a, b))
    return out


def _none(sf, s, e, name):
    """一个没有滚动视图的分支:出错态(名字带 Error,或者里面有「重试」)不算。"""
    if 'Error' in name or "'重试'" in sf.text[s:e]:
        return Result(ERR)
    return Result(NONE, sf, s, f'{name} 里没有滚动视图')


def reach(idx, sf, s, e, depth=0, seen=()):
    """[s, e) 这个 widget 表达式在各个分支里能不能下拉。"""
    if depth > 10 or s >= e:
        return [Result(UNKNOWN)]
    src = sf.text
    while src[s] == '(' and sf.pairs.get(s) == e - 1:
        s, e = _trim(sf, s + 1, e - 1)
    t = _ternary(sf, s, e)
    if t:
        return reach(idx, sf, *t[0], depth + 1, seen) + reach(idx, sf, *t[1], depth + 1, seen)
    c = _call(sf, s, e)
    if not c:
        name = src[s:e]
        if re.fullmatch(r'_?[a-z]\w*', name):
            got = _decl_returns(sf, name)
            if got is None:
                got = _assigns(sf, name, _member_span(sf, s)[0], s)  # 局部变量:用到它之前的每次赋值
            if got:
                return [r for a, b in got for r in reach(idx, sf, a, b, depth + 1, seen)]
        return [Result(UNKNOWN)]
    name, o = c
    if REFRESH.match(src, s):
        return [Result(REFRESHED, sf, s)]
    if name in SCROLL_NAMES:
        status, msg = _physics(sf, name, o)
        return [Result(status, sf, s, msg)]
    if name in UNJUDGED:
        return [Result(UNKNOWN)]
    builder = _named(sf, o, 'builder')
    if builder:
        rets = _fn_returns(sf, *builder)
        if rets is None and re.fullmatch(r'_?[a-z]\w*', src[builder[0]:builder[1]]):
            rets = _decl_returns(sf, src[builder[0]:builder[1]])
        res = [r for a, b in rets or [] for r in reach(idx, sf, a, b, depth + 1, seen)] or [Result(UNKNOWN)]
        # TweenAnimationBuilder / AnimatedBuilder 的 builder 常常只是把 child 包一层返回,真正的内容在 child: 里
        inner = _named(sf, o, 'child')
        if inner and any(r.status == UNKNOWN for r in res):
            res = [r for r in res if r.status != UNKNOWN] + reach(idx, sf, *inner, depth + 1, seen)
        return res
    # 同一文件里的方法:_body(v) / _list();widget.x()、foo.bar() 这种看不出来,不猜
    if re.match(r'_?[a-z]', name):
        got = _decl_returns(sf, name) if '.' not in name else None
        if got:
            return [r for a, b in got for r in reach(idx, sf, a, b, depth + 1, seen)]
        return [Result(UNKNOWN)]
    if LOADING.search(name):
        return [Result(LOAD)]
    # 项目里自己写的 widget:看它 build 返回什么
    base = name.split('.')[0]
    if base not in seen:
        osf, rets = idx.build_returns(base, sf)
        if rets:
            res = [r for a, b in rets for r in reach(idx, osf, a, b, depth + 1, seen + (base,))]
            if any(r.status != UNKNOWN for r in res):
                # 「这里没有能滚的」要报在用它的地方,不报在它自己的 build 里
                return [_none(sf, s, e, name) if r.status == NONE else r for r in res]
    # 包一层的 widget:看 child / body / children
    for slot in ('child', 'body'):
        v = _named(sf, o, slot)
        if v:
            return reach(idx, sf, *v, depth + 1, seen)
    ch = _named(sf, o, 'children')
    if ch and src[ch[0]] == '[':
        per = []
        for el in _list_elements(sf, *ch):
            per.append([Result(UNKNOWN)] if el is None else reach(idx, sf, *el, depth + 1, seen))
        flat = [r for rs in per for r in rs]
        bad = [r for r in flat if r.status == BAD]
        good = [r for r in flat if r.status in (OK, REFRESHED)]
        if good:
            # 兄弟里有能滚的就算能拉;但同一个位置上有的分支能滚、有的不能滚,不能滚的那支要报
            mixed = [r for rs in per if any(x.status in (OK, REFRESHED) for x in rs) for r in rs if r.status == NONE]
            return [Result(REFRESHED if any(r.status == REFRESHED for r in good) else OK)] + bad + mixed
        if any(r.status == UNKNOWN for r in flat):
            return [Result(UNKNOWN)] + bad
        if flat and all(r.status in (LOAD, ERR) for r in flat):
            return [Result(ERR if any(r.status == ERR for r in flat) else LOAD)]
        return [_none(sf, s, e, name)] + bad
    if name in PLACEHOLDER:
        return [Result(LOAD)]
    return [_none(sf, s, e, name)]


def _enclosing_open(sf, pos):
    best = None
    for o, c in sf.pairs.items():
        if o < pos < c and sf.text[o] in '([{' and (best is None or o > best):
            best = o
    return best


def _expr_around(sf, pos):
    """pos 所在的那个完整表达式(参数值 / return 的值 / 赋值号右边 / 箭头函数体)。"""
    src = sf.text
    o = _enclosing_open(sf, pos)
    if o is None:
        return None
    for a, b in _split(sf, o + 1, sf.pairs[o], ';' if src[o] == '{' else ','):
        if not a <= pos < b:
            continue
        m = re.match(r'\w+\s*:(?!:)', src[a:b])
        if m:
            a = _trim(sf, a + m.end(), b)[0]
        start = a
        for i in _top(sf, a, pos):
            if src.startswith('return', i) and not IDENT.match(src[i - 1]) and not IDENT.match(src[i + 6]):
                start = i + 6
            elif src.startswith('=>', i):
                start = i + 2
            elif src[i] == '=' and src[i - 1] not in '=!<>' and src[i + 1] not in '=>':
                start = i + 1
        return _trim(sf, start, b)
    return None


def _siblings(idx, sf, pos):
    """RefreshIndicator 所在分支点上所有分支的结果:三元的每一支、同一个函数的每个 return、同一个变量的每次赋值。"""
    src = sf.text
    i = pos - 1
    while i >= 0 and src[i].isspace():
        i -= 1
    if i < 0:
        return []
    if src[i] in '?:':
        span = _expr_around(sf, pos)
        return reach(idx, sf, *span) if span else []
    if src[i - 5:i + 1] == 'return' and not IDENT.match(src[i - 6]):
        o = pos
        while True:
            o = _enclosing_open(sf, o)
            if o is None:
                return []
            if src[o] == '{' and _is_fn_body(sf, o):
                break
        return [r for a, b in _block_returns(sf, o) for r in reach(idx, sf, a, b)]
    if src[i] == '=' and src[i - 1] not in '=!<>':
        m = re.search(r'([A-Za-z_]\w*)\s*=$', src[max(0, i - 80):i + 1])
        if not m:
            return []
        return [r for a, b in _assigns(sf, m.group(1), *_member_span(sf, pos)) for r in reach(idx, sf, a, b)]
    return []


def _report(res, ri_sf, ri_pos, what):
    line_no = res.sf.line_of(res.pos)
    if OK_MARK in res.sf.lines[line_no - 1]:
        return None
    via = '' if res.sf is ri_sf else f'(在 {ri_sf.path}:{ri_sf.line_of(ri_pos)} 的下拉刷新里)'
    return f'{res.sf.path}:{line_no}: {what}{via}'


def scan(sources):
    idx = Index(sources)
    hits = []
    for sf in sources:
        for r in REFRESH.finditer(sf.text):
            o = r.end() - 1
            if o not in sf.pairs:
                continue
            if OK_MARK in sf.lines[sf.line_of(r.start()) - 1]:
                continue
            # 1. RefreshIndicator 里面:每个分支都要有能滚的东西,滚动视图不满一屏也要拖得动
            child = _named(sf, o, 'child')
            for res in reach(idx, sf, *child) if child else []:
                if res.status == BAD:
                    hits.append(_report(res, sf, r.start(), res.msg))
                elif res.status == NONE:
                    hits.append(_report(res, sf, r.start(), f'{res.msg},这个分支拉不动下拉刷新'))
            # 2. RefreshIndicator 外面:和它并列的分支(常见的是空状态)没包进下拉刷新
            sib = _siblings(idx, sf, r.start())
            if any(x.status == REFRESHED for x in sib):
                for res in sib:
                    if res.status == NONE:
                        hits.append(_report(res, sf, r.start(),
                                            f'{res.msg},而且不在第 {sf.line_of(r.start())} 行的下拉刷新里:空着的时候拉不动'))
    return sorted({h for h in hits if h})


def main() -> int:
    sources = []
    for base in ROOTS:
        for root, _, files in os.walk(base):
            for f in files:
                if f.endswith('.dart'):
                    p = os.path.join(root, f)
                    sources.append(Source(p, open(p, encoding='utf-8').read()))
    hits = scan(sources)
    if hits:
        print('✗ 下拉刷新有拉不动的地方(改法见 scripts/check_refresh_pullable.py 开头):')
        for h in hits:
            print('  ' + h)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
