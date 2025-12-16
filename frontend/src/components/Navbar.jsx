import { NavLink } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import '../styles/App.css';

export default function Navbar() {
  const { user, logout } = useAuth();

  return (
    <nav className="navbar">
      {/* Links de navegação à esquerda */}
      <ul className="navbar-list">
        <li><NavLink className="navbar-link" to="/">Dashboard</NavLink></li>
        <li className="navbar-dropdown">
            <span className="navbar-link">Cadastros</span>
            <ul className="dropdown-menu">
              <li><NavLink className="navbar-link" to="/emissores">Emissores</NavLink></li>
              <li><NavLink className="navbar-link" to="/clientes">Clientes</NavLink></li>
              <li><NavLink className="navbar-link" to="/aliquota">Alíquota</NavLink></li>
            </ul>
        </li>
        <li><NavLink className="navbar-link" to="/emitir">Emitir Notas</NavLink></li>
        <li className="navbar-dropdown">
          <span className="navbar-link">Planilhas Modelo</span>
          <ul className="dropdown-menu">
            <li>
              <a
                className="navbar-link"
                href="http://10.0.0.172:6600/templates/clientes"
                target="_blank"
                rel="noopener noreferrer"
              >
                Modelo Clientes
              </a>
            </li>
            <li>
              <a
                className="navbar-link"
                href="http://10.0.0.172:6600/templates/notas"
                target="_blank"
                rel="noopener noreferrer"
              >
                Modelo Emitir Notas
              </a>
            </li>
          </ul>
        </li>
      </ul>

      {/* Informações do usuário e botão de logout à direita */}
      {user && (
        <div className="navbar-user-section">
          <span className="navbar-user-greeting">Olá, {user.name || user.email}</span>
          <button onClick={logout} className="navbar-logout-button">
            Sair
          </button>
        </div>
      )}
    </nav>
  );
}