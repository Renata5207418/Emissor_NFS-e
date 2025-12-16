import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { login, forgotPassword } from '../services/api';
import { Eye, EyeOff, X } from 'lucide-react';

function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showForgotModal, setShowForgotModal] = useState(false);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotLoading, setForgotLoading] = useState(false);

  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      const apiMessage =
        err?.response?.data?.message ||
        err?.response?.data?.error ||
        (err?.response?.status === 401 ? "E-mail ou senha incorretos." : null) ||
        err?.message ||
        "Falha no login. Verifique suas credenciais.";

      window.notify(apiMessage, "error");
    } finally {
      setLoading(false);
    }
  };

  const handleForgotSubmit = async (e) => {
      e.preventDefault();
      setForgotLoading(true);
      try {
        await forgotPassword(forgotEmail);

        window.notify("Link enviado! Verifique seu e-mail.", "success");
        setShowForgotModal(false);
        setForgotEmail('');
      } catch (err) {
        const msg = err?.response?.data?.detail || "Erro ao enviar solicitação.";
        window.notify(msg, "error");
      } finally {
        setForgotLoading(false);
      }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="logo-container">
          <img
            src="/Logo-scryta.svg"
            alt="Logo Scryta"
            className="logo"
          />
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email:</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="exemplo@email.com"
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Senha:</label>
            <div className="password-wrapper">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
              />
              <button
                type="button"
                className="eye-icon-btn"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex="-1"
              >
                {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>

            <div style={{ textAlign: 'right', marginTop: '5px' }}>
                <button
                    type="button"
                    onClick={() => setShowForgotModal(true)}
                    style={{
                        background: 'none',
                        border: 'none',
                        color: '#666',
                        fontSize: '0.85rem',
                        cursor: 'pointer',
                        textDecoration: 'underline'
                    }}
                >
                    Esqueceu a senha?
                </button>
            </div>
          </div>

          <button type="submit" className="btn" disabled={loading}>
            {loading ? 'Entrando...' : 'Entrar'}
          </button>
        </form>

        <p className="auth-switch-link">
          Não tem uma conta? <Link to="/register">Cadastre-se</Link>
        </p>
      </div>

      {/* --- MODAL DE ESQUECI A SENHA --- */}
      {showForgotModal && (
        <div className="modal-overlay" onClick={() => setShowForgotModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
                <h3>Recuperar Senha</h3>
                <button onClick={() => setShowForgotModal(false)} style={{background:'none', border:'none', cursor:'pointer'}}>
                    <X size={24} />
                </button>
            </div>

            <p style={{fontSize: '0.9rem', color: '#666', marginBottom: '1rem'}}>
                Digite seu e-mail cadastrado. Enviaremos um link para você redefinir sua senha.
            </p>

            <form onSubmit={handleForgotSubmit}>
                <div className="form-group" style={{textAlign: 'left'}}>
                    <label htmlFor="forgot-email">E-mail:</label>
                    <input
                        id="forgot-email"
                        type="email"
                        required
                        value={forgotEmail}
                        onChange={(e) => setForgotEmail(e.target.value)}
                        placeholder="seu@email.com"
                    />
                </div>
                <div className="modal-actions">
                    <button type="button" className="btn-secondary" onClick={() => setShowForgotModal(false)}>
                        Cancelar
                    </button>
                    <button type="submit" className="btn" disabled={forgotLoading}>
                        {forgotLoading ? 'Enviando...' : 'Enviar Link'}
                    </button>
                </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

export default LoginPage;