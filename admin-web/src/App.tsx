import { Navigate, Route, Routes } from 'react-router-dom'
import { useState } from 'react'

import ConsoleLayout from './layouts/ConsoleLayout'
import LoginPage from './pages/LoginPage'
import { getToken } from './api'

/**
 * 路由。
 *
 * ## 登录态为什么要放进 state
 *
 * 第一版直接写 `getToken() ? <ConsoleLayout/> : <Navigate to="/login"/>`。
 * 看着没问题,实际登录完卡在登录页不动 —— `getToken()` 读的是 localStorage,
 * **改它不会触发 React 重渲染**:`navigate('/merchants')` 换了地址,
 * 但这一层的 element 是上一次渲染算出来的 `<Navigate to="/login">`,
 * 于是又被弹回登录页。token 存进去了、接口也通、就是进不去。
 *
 * 放进 state,登录成功时显式 `setAuthed(true)`,这一层才会跟着变。
 */
export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken())

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onAuthed={() => setAuthed(true)} />} />
      <Route
        path="/*"
        element={authed
          ? <ConsoleLayout onLogout={() => setAuthed(false)} />
          : <Navigate to="/login" replace />}
      />
    </Routes>
  )
}
