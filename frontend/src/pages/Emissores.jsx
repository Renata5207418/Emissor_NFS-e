import { useState, useEffect, useRef } from "react";
import {
  getEmitters,
  createEmitter,
  updateEmitter,
  deleteEmitter,
  uploadEmitterCertificate,
} from "../services/api";
import "../styles/EmissoresClientes.css";

// ---------------- UTILS ----------------
function sanitizeDocument(value) {
  return value ? value.replace(/\D/g, "") : "";
}
function formatCnpj(value) {
  if (!value) return "";
  const sanitizedValue = sanitizeDocument(value);
  if (sanitizedValue.length === 14) {
    return sanitizedValue.replace(
      /(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/,
      "$1.$2.$3/$4-$5"
    );
  }
  return value;
}

// ---- helpers para status do certificado ----
function daysUntil(dateStr) {
  if (!dateStr) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(`${dateStr}T23:59:59`);
  const diffMs = target - today;
  return Math.floor(diffMs / (1000 * 60 * 60 * 24));
}

function getCertStatus(validadeStr) {
  const d = daysUntil(validadeStr);
  if (d === null) return { text: "—", level: "unknown", days: null };
  if (d < 0) return { text: `Vencido há ${Math.abs(d)}d`, level: "expired", days: d };
  if (d <= 15) return { text: `Vence em ${d}d`, level: "warning", days: d };
  return { text: "Válido", level: "ok", days: d };
}

function formatDateBR(iso) {
  if (!iso) return "-";
  const parts = iso.split("-");
  if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString("pt-BR");
}

export default function Emissores() {
  const [emissores, setEmissores] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [emissorSelecionado, setEmissorSelecionado] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const errorRef = useRef(null);
  const [termoBusca, setTermoBusca] = useState("");
  const [formData, setFormData] = useState({
    razaoSocial: "",
    cnpj: "",
    regimeTributacao: "",
    cep: "",
    logradouro: "",
    numero: "",
    complemento: "",
    bairro: "",
    cidade: "",
    uf: "",
    codigoIbge: "",
    certificado: null,
    senhaCertificado: "",
  });

  // Carregar emissores da API
  useEffect(() => {
    async function fetchEmitters() {
      const data = await getEmitters();
      setEmissores(data);
    }
    fetchEmitters();
  }, []);

  // Scroll para mensagem de erro
  useEffect(() => {
    if (errorMessage && errorRef.current) {
      errorRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [errorMessage]);

  const handleInputChange = (e) => {
    const { name, value, files } = e.target;
    if (files) {
      setFormData({ ...formData, [name]: files[0] });
    } else {
      setFormData({ ...formData, [name]: value });
    }
  };

  const handleCepChange = async (e) => {
    const cep = e.target.value.replace(/\D/g, "");
    setFormData({ ...formData, cep });

    if (cep.length === 8) {
      try {
        const response = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
        const data = await response.json();

        if (!data.erro) {
          setFormData((prev) => ({
            ...prev,
            logradouro: data.logradouro || "",
            bairro: data.bairro || "",
            cidade: data.localidade || "",
            uf: data.uf || "",
            codigoIbge: data.ibge || "",
          }));
        }
      } catch {
        // silencia erro de CEP
      }
    }
  };

  const handleAbrirModal = (emissorParaEditar = null) => {
    setErrorMessage("");
    setEmissorSelecionado(emissorParaEditar);

    if (emissorParaEditar) {
      setFormData({
        razaoSocial: emissorParaEditar.razaoSocial || "",
        cnpj: emissorParaEditar.cnpj || "",
        regimeTributacao: emissorParaEditar.regimeTributacao || "",
        cep: emissorParaEditar.cep || "",
        logradouro: emissorParaEditar.logradouro || "",
        numero: emissorParaEditar.numero || "",
        complemento: emissorParaEditar.complemento || "",
        bairro: emissorParaEditar.bairro || "",
        cidade: emissorParaEditar.cidade || "",
        uf: emissorParaEditar.uf || "",
        codigoIbge: emissorParaEditar.codigoIbge || "",
        certificado: null,
        senhaCertificado: "",
      });
    } else {
      setFormData({
        razaoSocial: "",
        cnpj: "",
        regimeTributacao: "",
        cep: "",
        logradouro: "",
        numero: "",
        complemento: "",
        bairro: "",
        cidade: "",
        uf: "",
        codigoIbge: "",
        certificado: null,
        senhaCertificado: "",
      });
    }

    setShowModal(true);
  };

  const handleSalvar = async (e) => {
    e.preventDefault();
    setErrorMessage("");

    if (!formData.cnpj || !formData.razaoSocial) {
      setErrorMessage("CNPJ e Razão Social são obrigatórios.");
      return;
    }
    if (!formData.certificado && !emissorSelecionado) {
      setErrorMessage("É obrigatório anexar um certificado digital.");
      return;
    }

    try {
      let emissorId = null;

      // 🔹 Se estiver editando emissor existente
      if (emissorSelecionado && emissorSelecionado._id) {
        const payload = {
          razaoSocial: formData.razaoSocial,
          cnpj: sanitizeDocument(formData.cnpj),
          regimeTributacao: formData.regimeTributacao,
          cep: formData.cep,
          logradouro: formData.logradouro,
          numero: formData.numero,
          complemento: formData.complemento,
          bairro: formData.bairro,
          cidade: formData.cidade,
          uf: formData.uf,
          codigoIbge: formData.codigoIbge,
        };

        await updateEmitter(emissorSelecionado._id, payload);
        emissorId = emissorSelecionado._id;

        // Se o usuário anexou novo certificado
        if (formData.certificado) {
          await uploadEmitterCertificate(
            emissorId,
            formData.certificado,
            formData.senhaCertificado
          );
        }
      } else {
        // 🔹 Criação de novo emissor
        const formPayload = new FormData();
        formPayload.append("razaoSocial", formData.razaoSocial);
        formPayload.append("cnpj", sanitizeDocument(formData.cnpj));
        formPayload.append("regimeTributacao", formData.regimeTributacao);
        formPayload.append("cep", formData.cep);
        formPayload.append("logradouro", formData.logradouro);
        formPayload.append("numero", formData.numero);
        formPayload.append("complemento", formData.complemento);
        formPayload.append("bairro", formData.bairro);
        formPayload.append("cidade", formData.cidade);
        formPayload.append("uf", formData.uf);
        formPayload.append("codigoIbge", formData.codigoIbge);
        formPayload.append("certificado", formData.certificado);
        formPayload.append("senhaCertificado", formData.senhaCertificado);

        // 🚀 Usa função de api.js (envia token automaticamente)
        const data = await createEmitter(formPayload);
        emissorId = data.id;
      }

      // Atualiza lista de emissores
      const emissoresAtualizados = await getEmitters();
      setEmissores(emissoresAtualizados);
      setShowModal(false);
      window.notify("Emissor salvo com sucesso!");

    } catch (err) {
  console.error(err);

  // Captura mensagem clara do backend (FastAPI)
  let message = "Erro ao salvar emissor.";

  if (err.response) {
    if (err.response.data && err.response.data.detail) {
      message = err.response.data.detail; // <- aqui vem o texto do FastAPI
    } else if (typeof err.response.data === "string") {
      message = err.response.data;
    }
  } else if (err.message) {
    message = err.message;
  }
  setErrorMessage(message);
}
};
  const handleDelete = async (id) => {
  const confirma = await window.confirmDialog("Deseja realmente excluir este emissor?");
  if (!confirma) return;

  try {
    await deleteEmitter(id);
    const data = await getEmitters();
    setEmissores(data);
    window.notify("Emissor excluído com sucesso!");
  } catch (err) {
    console.error(err);
    window.notify("Erro ao excluir emissor.");
  }
};


  const emissoresFiltrados = emissores.filter((emissor) => {
    if (!emissor) return false;
    const busca = termoBusca.toLowerCase();
    const razaoSocial = String(emissor.razaoSocial || "").toLowerCase();
    const cnpj = String(emissor.cnpj || "");
    return (
      razaoSocial.includes(busca) ||
      cnpj.includes(busca)
    );
  });

  return (
    <div className="container">
      <h1>Cadastro de Emissores</h1>
      <button className="btn" onClick={() => handleAbrirModal()}>
        + Incluir Emissor
      </button>
      <div className="search-container" style={{ marginTop: "20px" }}>
        <input
          type="text"
          placeholder="Pesquisar por razão social, CNPJ..."
          className="search-input"
          value={termoBusca}
          onChange={(e) => setTermoBusca(e.target.value)}
        />
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Razão Social</th>
            <th>CNPJ</th>
            <th>Regime</th>
            <th className="status-col">Status do Certificado</th>
            <th>Validade</th>
            <th>Ações</th>
          </tr>
        </thead>
        <tbody>
          {emissoresFiltrados.map((e) => {
            const status = getCertStatus(e.validade_certificado);
            return (
              <tr key={e._id}>
                <td>{e.razaoSocial || "-"}</td>
                <td>{formatCnpj(e.cnpj)}</td>
                <td>{e.regimeTributacao || "-"}</td>

                {/* status centralizado */}
                <td className="status-col">
                  <span
                    className={`badge ${status.level}`}
                    title={
                      e.validade_certificado
                        ? `Validade: ${formatDateBR(e.validade_certificado)}`
                        : "Sem data"
                    }
                  >
                    {status.text}
                  </span>
                  {status.level === "warning" && (
                    <span className="hint"></span>
                  )}
                </td>

                {/* validade em dd/mm/aaaa */}
                <td>{formatDateBR(e.validade_certificado)}</td>

                <td>
                  <button className="btn-link" onClick={() => handleAbrirModal(e)}>
                    Editar
                  </button>{" "}
                  |{" "}
                  <button
                    className="btn-link delete"
                    onClick={() => handleDelete(e._id)}
                  >
                    Excluir
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {showModal && (
        <div className="modal-overlay">
          <div className="modal">
            <button className="modal-close" onClick={() => setShowModal(false)}>
              &times;
            </button>
            <h2>{emissorSelecionado ? "Editar Emissor" : "Novo Emissor"}</h2>
            <form onSubmit={handleSalvar}>
              {errorMessage && (
                <div ref={errorRef} className="error-message">
                  {errorMessage}
                </div>
              )}

              <div className="form-grid">
                <label>
                  Razão Social:
                  <input
                    type="text"
                    name="razaoSocial"
                    value={formData.razaoSocial}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  CNPJ:
                  <input
                    type="text"
                    name="cnpj"
                    value={formData.cnpj}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Regime de Tributação:
                  <select
                    name="regimeTributacao"
                    value={formData.regimeTributacao}
                    onChange={handleInputChange}
                  >
                    <option value="">Selecione...</option>
                    <option value="Simples Nacional">Simples Nacional</option>
                    <option value="Lucro Presumido">Lucro Presumido</option>
                    <option value="Lucro Real">Lucro Real</option>
                    <option value="MEI">MEI</option>
                  </select>
                </label>

                <label>
                  Certificado (.pfx):
                  <div className="custom-file-upload">
                    <label htmlFor="certificado-upload" className="upload-button">
                      Escolher Arquivo
                    </label>
                    <span className="file-name">
                      {formData.certificado
                        ? formData.certificado.name
                        : "Nenhum arquivo escolhido"}
                    </span>
                    <input
                      id="certificado-upload"
                      type="file"
                      name="certificado"
                      accept=".pfx,.pem"
                      onChange={handleInputChange}
                    />
                  </div>
                </label>
                <label>
                  Senha do Certificado:
                  <input
                    type="password"
                    name="senhaCertificado"
                    value={formData.senhaCertificado}
                    onChange={handleInputChange}
                  />
                </label>
              </div>

              <h3 style={{ marginTop: "20px" }}>Endereço</h3>
              <div className="form-grid">
                <label>
                  CEP:
                  <input
                    type="text"
                    name="cep"
                    value={formData.cep}
                    onChange={handleCepChange}
                  />
                </label>
                <label>
                  Logradouro:
                  <input
                    type="text"
                    name="logradouro"
                    value={formData.logradouro}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Número:
                  <input
                    type="text"
                    name="numero"
                    value={formData.numero}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Complemento:
                  <input
                    type="text"
                    name="complemento"
                    value={formData.complemento}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Bairro:
                  <input
                    type="text"
                    name="bairro"
                    value={formData.bairro}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Cidade:
                  <input
                    type="text"
                    name="cidade"
                    value={formData.cidade}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Estado:
                  <input
                    type="text"
                    name="uf"
                    value={formData.uf}
                    onChange={handleInputChange}
                  />
                </label>
                <label>
                  Cód. Município:
                  <input
                    type="text"
                    name="codigoIbge"
                    value={formData.codigoIbge}
                    onChange={handleInputChange}
                    readOnly
                  />
                </label>
              </div>

              <div className="modal-actions">
                <button type="submit" className="btn">
                  Salvar
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowModal(false)}
                >
                  Cancelar
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
