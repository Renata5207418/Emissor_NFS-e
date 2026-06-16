import React, { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { resetPassword } from '../services/api'; // Import correto
import { Eye, EyeOff } from 'lucide-react';

function ResetPasswordPage() {
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const token = searchParams.get('token');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      window.notify("As senhas não conferem.", "error");
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, password);

      window.notify("Senha alterada! Faça login.", "success");
      setTimeout(() => navigate('/login'), 2000);
    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro: Link expirado ou inválido.";
      window.notify(msg, "error");
    } finally {
      setLoading(false);
    }
  };

  if (!token) return <div className="auth-page"><div className="auth-card">Link inválido.</div></div>;

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h2>Nova Senha</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Nova Senha:</label>
            <div className="password-wrapper">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
              />
               <button type="button" className="eye-icon-btn" onClick={() => setShowPassword(!showPassword)}>
                {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>
          </div>

          <div className="form-group">
            <label>Confirmar Senha:</label>
             <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
          </div>

          <button type="submit" className="btn" disabled={loading}>
            {loading ? 'Salvando...' : 'Salvar Nova Senha'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default ResetPasswordPage;