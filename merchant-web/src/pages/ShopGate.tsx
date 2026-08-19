import { Button, Card, Result, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import {
  ApiError, BrandShop, getShopId, getToken, Merchant, myBrand, myShop,
  setShopId, switchShop,
} from '../api'
import ConsoleLayout from '../layouts/ConsoleLayout'

/** 门禁:未登录→登录页;无店/被驳回→引导去 App;待审→轮询;过审→工作台 */
export default function ShopGate() {
  const [shop, setShop] = useState<Merchant | null>(null)
  const [shops, setShops] = useState<BrandShop[]>([])
  const [noShop, setNoShop] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      // **先问有哪些店,再问当前这家**。顺序不能反 —— 连锁账号在没选店时
      // /merchants/me 是 404(后端不猜是哪家),先调它会把连锁老板
      // 一路带进"还没有店铺"的引导页。
      const brand = await myBrand()
      setShops(brand.shops)
      if (brand.shops.length === 0) {
        setNoShop(true)
        setShop(null)
        return
      }
      // 存的门店已经不在可操作范围里(被移出品牌/店被划走)就退回第一家,
      // 否则会一直卡在 404
      const current = getShopId()
      if (!current || !brand.shops.some((s) => s.id === current)) {
        setShopId(brand.shops[0].id)
      }
      setShop(await myShop())
      setNoShop(false)
      setError(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNoShop(true)
      else if (!(e instanceof ApiError && e.status === 401)) {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }, [])

  useEffect(() => {
    if (!getToken()) return
    load()
  }, [load])

  // 待审核期间轮询,管理员一点通过自动进工作台
  useEffect(() => {
    if (shop?.status !== 'pending') return
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [shop?.status, load])

  if (!getToken()) return <Navigate to="/login" replace />

  if (noShop || shop?.status === 'rejected') {
    return (
      <Center>
        <Result
          status="info"
          title={noShop ? '还没有店铺' : `入驻申请被驳回:${shop?.reject_reason}`}
          subTitle={
            <>
              请先在「超级赞商家」App 完成入驻(证照拍照上传手机更方便),
              审核通过后网页版自动可用。
              <br />下载:chaojizan.cc/download
            </>
          }
          extra={
            <>
              <Button onClick={load}>我已提交,刷新</Button>
              {/* 连锁:一家新店被驳回,不该把整个总部也挡在门外 */}
              {shops.length > 1 && (
                <Button type="link" onClick={() => {
                  const other = shops.find(
                    (s) => s.id !== shop?.id && s.status === 'approved')
                  if (other) switchShop(other.id)
                }}>切换到其他门店</Button>
              )}
            </>
          }
        />
      </Center>
    )
  }

  if (error) {
    return (
      <Center>
        <Result
          status="warning"
          title="加载失败"
          subTitle={error}
          extra={<Button type="primary" onClick={load}>重试</Button>}
        />
      </Center>
    )
  }

  if (!shop) {
    return <Center><Spin size="large" /></Center>
  }

  if (shop.status === 'pending') {
    return (
      <Center>
        <Result
          status="info"
          title={`「${shop.name}」入驻审核中`}
          subTitle={shop.biz_type === 'hotel'
            ? '平台正在核对营业执照与特种行业许可证,通过后自动进入工作台'
            : '平台正在核对食品经营许可证,通过后自动进入工作台'}
          // 连锁新店在审时,别把总部也一起挡在门外
          extra={shops.length > 1 && (
            <Button onClick={() => {
              const other = shops.find(
                (s) => s.id !== shop.id && s.status === 'approved')
              if (other) switchShop(other.id)
            }}>切换到其他门店</Button>
          )}
        />
      </Center>
    )
  }

  return <ConsoleLayout shop={shop} shops={shops} onShopChanged={load} />
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: 'var(--sz-paper)',
    }}>
      <Card style={{ minWidth: 420 }}>{children}</Card>
    </div>
  )
}
