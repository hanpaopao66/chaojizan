#!/usr/bin/env python3
"""把一个目录打成**可复现**的 zip:同样的文件永远得到同样的字节(同样的 SHA-256)。

- 条目按路径排序;时间一律 1980-01-01 00:00:00;权限一律 0644;
- 不写目录条目、不写额外字段;DEFLATE 固定 9 级。

用法:python3 scripts/zip_reproducible.py <目录> <输出.zip>
小程序的线上 SHA-256(详情页公示)和开源仓里跑这个脚本的结果对得上,才算「审核看的就是上线的那一份」。
"""
import hashlib
import sys
import zipfile
from pathlib import Path

EPOCH = (1980, 1, 1, 0, 0, 0)


def build(src: Path, out: Path) -> str:
    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.name.startswith("."))
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        for p in files:
            info = zipfile.ZipInfo(p.relative_to(src).as_posix(), date_time=EPOCH)
            info.external_attr = 0o644 << 16
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return hashlib.sha256(out.read_bytes()).hexdigest()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
