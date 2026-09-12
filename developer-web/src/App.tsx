import { useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { getToken } from './api'
import ConsoleLayout from './components/ConsoleLayout'
import LoginPage from './pages/LoginPage'

/** 登录态放进 state:localStorage 变了不会触发重渲染(平台后台踩过同一个坑) */
export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken())
  return (
    <Routes>
      <Route path="/login" element={<LoginPage onAuthed={() => setAuthed(true)} />} />
      <Route path="/*" element={authed ? <ConsoleLayout onLogout={() => setAuthed(false)} /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}
