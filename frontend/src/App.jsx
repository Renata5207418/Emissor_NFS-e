import { Routes, Route } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Clientes from "./pages/Clientes";
import Emissores from "./pages/Emissores";
import EmitirNota from "./pages/EmitirNota";
import LoginPage from "./pages/Login";
import RegisterPage from "./pages/Register";
import AppLayout from "./components/AppLayout";
import ProtectedRoute from "./components/ProtectedRoute";
import Aliquota from "./pages/Aliquota";
import ResetPasswordPage from './pages/ResetPasswordPage';
import './styles/App.css';
import { useState, useEffect } from "react";
import Notification from "./components/Notification";

function App() {
  const [alertMessage, setAlertMessage] = useState(null);
  const [confirmData, setConfirmData] = useState(null);

  useEffect(() => {
    // ✅ Toast global
    window.notify = (message, type = "success") => {
      setAlertMessage({ message, type });
    };

    // ✅ Modal de confirmação global
    window.confirmDialog = (message) => {
      return new Promise((resolve) => {
        setConfirmData({ message, resolve });
      });
    };
  }, []);

  return (
    <>
      <Routes>
        {/* Rotas públicas */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />

        {/* Rotas protegidas */}
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/emissores" element={<Emissores />} />
            <Route path="/clientes" element={<Clientes />} />
            <Route path="/aliquota" element={<Aliquota />} />
            <Route path="/emitir" element={<EmitirNota />} />
          </Route>
        </Route>

        <Route
          path="*"
          element={
            <div style={{ textAlign: 'center', marginTop: '50px' }}>
              <h1>404: Página não encontrada</h1>
            </div>
          }
        />
      </Routes>

      <Notification
        alert={alertMessage}
        confirm={confirmData}
        onClose={() => {
          setAlertMessage(null);
          setConfirmData(null);
        }}
      />
    </>
  );
}

export default App;
