import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
// 令牌:由 scripts/gen_tokens.py 从 packages/shared/lib/src/brand.dart 生成。
// tokens.css 要在组件样式之前进 bundle,所以放在 App 之后、其余样式之前。
import './tokens.css'
import { szLight } from './theme'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {/* 主色从令牌来,不要再写死十六进制:
        这里原本是 '#FF5A1F',而 docs/BRAND.md 里那个色标着「已废弃」——
        于是商家后台和 App 长成了两个产品。 */}
    <ConfigProvider locale={zhCN} theme={szLight}>
      {/* basename 去尾斜杠:/merchant 与 /merchant/ 都能命中路由 */}
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>,
)
