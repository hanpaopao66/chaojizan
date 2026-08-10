"""ArkTS 静态自检:没有 DevEco 也要能发现导入/导出对不上。

查三类问题(都是编译期才会炸、但改起来最烦的):
1. import 的符号在目标文件里没 export
2. import 的相对路径指向不存在的文件
3. import 了却没用到(留着会被 ArkTS 报 unused)
"""
import re, sys, pathlib

root = pathlib.Path(sys.argv[1])
files = sorted(root.rglob('*.ets'))

def exports_of(p):
    s = p.read_text()
    out = set()
    for m in re.finditer(r'export\s+(?:default\s+)?(?:abstract\s+)?(?:async\s+)?'
                         r'(?:class|struct|interface|enum|function|const|let|type)\s+(\w+)', s):
        out.add(m.group(1))
    for m in re.finditer(r'export\s*\{([^}]*)\}', s):
        for part in m.group(1).split(','):
            name = part.strip().split(' as ')[-1].strip()
            if name:
                out.add(name)
    return out

exp = {p.resolve(): exports_of(p) for p in files}
problems = []
for p in files:
    s = p.read_text()
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*'(\.[^']+)'", s):
        names = [n.strip() for n in m.group(1).split(',') if n.strip()]
        target = (p.parent / m.group(2)).resolve()
        cand = target.with_suffix('.ets')
        if not cand.exists():
            problems.append(f"{p.relative_to(root)}: 路径不存在 {m.group(2)}")
            continue
        have = exp.get(cand, set())
        for n in names:
            if n not in have:
                problems.append(f"{p.relative_to(root)}: 从 {m.group(2)} 导入的 `{n}` 没有被 export")
            # 用没用到:去掉 import 行本身再找
            body = s[:m.start()] + s[m.end():]
            if not re.search(r'\b' + re.escape(n) + r'\b', body):
                problems.append(f"{p.relative_to(root)}: 导入了 `{n}` 但没用到")

print(f"扫了 {len(files)} 个 .ets")
if problems:
    for x in problems:
        print("  ★", x)
    print(f"\n共 {len(problems)} 处")
else:
    print("导入导出全部对得上")
