import { Button, Card, Result, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import { ApiError, getToken, Merchant, myShop } from '../api'
import ConsoleLayout from '../layouts/ConsoleLayout'

/** 门禁:未登录→登录页;无店/被驳回→引导去 App;待审→轮询;过审→工作台 */
export default function ShopGate() {
  const [shop, setShop] = useState<Merchant | null>(null)
  const [noShop, setNoShop] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
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
          extra={<Button onClick={load}>我已提交,刷新</Button>}
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
        />
      </Center>
    )
  }

  return <ConsoleLayout shop={shop} onShopChanged={load} />
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: '#f5f5f5',
    }}>
      <Card style={{ minWidth: 420 }}>{children}</Card>
    </div>
  )
}
