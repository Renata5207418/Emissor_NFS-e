import { useEffect } from "react";
import ReactDOM from "react-dom";
import "../styles/Notification.css";

export default function Notification({ alert, onClose, confirm }) {
  useEffect(() => {
    if (alert) {
      const timer = setTimeout(onClose, 2800);
      return () => clearTimeout(timer);
    }
  }, [alert, onClose]);

  if (confirm) {
    return ReactDOM.createPortal(
      <div className="confirm-overlay">
        <div className="confirm-box">
          <p className="confirm-message">{confirm.message}</p>
          <div className="confirm-buttons">
            <button className="confirm-btn ok"
              onClick={() => { confirm.resolve(true); onClose(); }}>
              OK
            </button>
            <button className="confirm-btn cancel"
              onClick={() => { confirm.resolve(false); onClose(); }}>
              Cancelar
            </button>
          </div>
        </div>
      </div>,
      document.body
    );
  }

  if (alert) {
    return ReactDOM.createPortal(
      <div className={`toast-container ${alert.type}`}>
        <div className="toast-box">{alert.message}</div>
      </div>,
      document.body
    );
  }

  return null;
}
