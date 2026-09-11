import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.jsx'
// 全局重置 + /screen 的深色底(只剩这些,见文件抬头)
import './styles.css'
// 官网浅色版的公共样式(顶栏、页脚、令牌、卡片、表格)。放在 styles.css 之后:
// 两边同优先级的规则以这份为准
import './site.css'
import './home.css'

createRoot(document.getElementById('root')).render(<App />)
