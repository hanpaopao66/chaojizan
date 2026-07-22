"""存量商家城市回填:逆地理批量跑一次(需 .env 配 TIANDITU_SERVER_KEY)。

在 server/ 目录下运行:python -m scripts.backfill_city
幂等:只处理 city 为空的商家;失败的留空下次再跑或后台人工填。
"""
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Merchant
from app.services.geo_city import city_of


async def main():
    async with SessionLocal() as db:
        shops = (await db.scalars(
            select(Merchant).where(Merchant.city == ""))).all()
        print(f"待回填商家:{len(shops)} 家")
        done = 0
        for shop in shops:
            city = await city_of(shop.lat, shop.lng)
            if city:
                shop.city = city
                done += 1
                print(f"  #{shop.id} {shop.name} → {city}")
            await asyncio.sleep(0.2)  # 天地图免费配额限速,别打太快
        await db.commit()
        print(f"完成:回填 {done} 家,失败/未解析 {len(shops) - done} 家(留空人工填)")


if __name__ == "__main__":
    asyncio.run(main())
