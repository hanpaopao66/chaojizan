"""存量 uploads 迁移(#124/#125):分公开/私密灌进对象存储。

**幂等,可重跑。** 跑完打印两边对账。

判定「哪些是私密的」不靠猜文件名,靠查库:
rider_profiles.id_card_photo_url / health_cert_photo_url、
merchants.license_image_url、orders.delivery_photo_url —— 这四列里出现过的
文件就是证照类,其余按公开处理。

**数据库里的 URL 一个字都不改。** 库里存的全是 `/uploads/xxx.jpg` 相对路径,
批量改一旦要回滚就全乱套。老路径的行为由 routers/uploads.py 的 legacy_file
分流:私密的进 private 存储(key = `legacy/{文件名}`),访问要过鉴权;
公开的仍然直出。

用法(在 server/ 下):
    python -m scripts.migrate_uploads            # 真跑
    python -m scripts.migrate_uploads --dry-run  # 只看要动什么
"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.services import storage  # noqa: E402

PRIVATE_COLUMNS = [
    ("rider_profiles", "id_card_photo_url"),
    ("rider_profiles", "health_cert_photo_url"),
    ("merchants", "license_image_url"),
    ("orders", "delivery_photo_url"),
]


async def private_filenames() -> set[str]:
    """查库拿到所有证照类文件名(不含目录)。"""
    names: set[str] = set()
    async with SessionLocal() as db:
        for table, col in PRIVATE_COLUMNS:
            try:
                rows = (await db.execute(text(
                    f"SELECT DISTINCT {col} FROM {table} "
                    f"WHERE {col} IS NOT NULL AND {col} <> ''"))).all()
            except Exception as e:
                print(f"  ! 跳过 {table}.{col}: {type(e).__name__}")
                continue
            for (url,) in rows:
                names.add(Path(str(url)).name)
    return names


def main(dry_run: bool) -> None:
    upload_dir = storage.UPLOAD_DIR
    if not upload_dir.exists():
        print("uploads/ 不存在,无事可做")
        return

    private = asyncio.run(private_filenames())
    print(f"库里引用的证照类文件 {len(private)} 个")

    files = [f for f in upload_dir.rglob("*")
             if f.is_file() and not f.name.startswith(".")]
    print(f"uploads/ 下共 {len(files)} 个文件")

    backend = storage.backend()
    print(f"目标后端:{backend.name}")

    moved_private = moved_public = skipped = failed = 0
    for f in files:
        rel = f.relative_to(upload_dir).as_posix()
        is_priv = f.name in private
        key = f"legacy/{f.name}" if is_priv else rel
        try:
            if backend.exists(key, private=is_priv):
                skipped += 1          # 幂等:已经在了就不重复写
                continue
            if dry_run:
                print(f"  [dry] {'私密' if is_priv else '公开'} {rel} → {key}")
            else:
                backend.put(f.read_bytes(), key, private=is_priv)
            if is_priv:
                moved_private += 1
            else:
                moved_public += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ {rel}: {type(e).__name__}: {e}")

    print(f"\n公开 {moved_public} 个 / 私密 {moved_private} 个 / "
          f"已存在跳过 {skipped} 个 / 失败 {failed} 个")

    if dry_run:
        print("(dry-run,未写入)")
        return

    # 对账:库里引用的每一个证照文件,都必须在私密存储里查得到。
    # 查不到就是"老 URL 还能匿名访问"的漏网之鱼,必须报出来
    missing = [n for n in private
               if not backend.exists(f"legacy/{n}", private=True)]
    if missing:
        print(f"\n⚠ 有 {len(missing)} 个证照文件没能进私密存储(源文件可能已丢失):")
        for n in sorted(missing)[:10]:
            print(f"    {n}")
        print("  这些老 URL 现在会 404 —— 比继续公开可读好,但要人工确认")
    else:
        print("\n✓ 对账通过:库里引用的证照文件全部已在私密存储")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
