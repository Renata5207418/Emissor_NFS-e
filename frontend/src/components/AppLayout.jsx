import { Outlet } from 'react-router-dom';
import Navbar from './Navbar';
import Footer from './Footer';

// Este componente serve como o "molde" para as páginas internas da aplicação
export default function AppLayout() {
  return (
    <div className="app">
      <Navbar />
      <main>
        {/* O <Outlet> é onde o conteúdo da página (Dashboard, Clientes, etc.) será renderizado */}
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}