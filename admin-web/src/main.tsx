import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
// 令牌:由 scripts/gen_tokens.py 从 packages/shared/lib/src/brand.dart 生成,
// 和 App、商家后台同一个源。**不要手改 tokens.css / theme.ts**
import './tokens.css'
import { szLight } from './theme'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={szLight}>
      {/* basename 去尾斜杠:/admin-console 与 /admin-console/ 都能命中 */}
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>,
)
