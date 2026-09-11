import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.jsx'
import './styles.css'
// 首页 v3 的样式。放在 styles.css 之后:两边同优先级的规则以这份为准
import './home.css'

createRoot(document.getElementById('root')).render(<App />)
