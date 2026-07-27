import { Navigate, Route, Routes } from 'react-router-dom'

import ShopGate from './pages/ShopGate'
import LoginPage from './pages/LoginPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/*" element={<ShopGate />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
