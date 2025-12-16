import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import {
  apiClient,
  getClients,
  createClient,
  updateClient,
  deleteClient,
  getEmitters,
} from "../services/api";
import "../styles/EmissoresClientes.css";


// ---------------- UTILS ----------------

function translateErrorMessage(rawError) {
  if (!rawError) return "Erro desconhecido.";
  const err = String(rawError).toLowerCase();

  if (err.includes("expecting value") || err.includes("char 0")) {
    return "Falha de comunicação com a API da Receita. Pode ser uma instabilidade temporária. Tente cadastrar este cliente manualmente.";
  }
  if (err.includes("nome não informado") && err.includes("não conseguiu preencher")) {
    return "O nome não foi fornecido na planilha e a busca automática pelo CNPJ/CPF falhou.";
  }
  if (err.includes("já cadastrado") || err.includes("duplicate key")) {
    return "Este CNPJ/CPF ou e-mail já existe no sistema.";
  }
  if (err.includes("planilha inválida")) {
    return "O formato da planilha não corresponde ao modelo oficial. Baixe o modelo em 'Importar Planilha' e preencha nele.";
  }

  return rawError;
}

function sanitizeDocument(value) {
  return value ? value.replace(/\D/g, "") : "";
}

function formatCnpjCpf(value) {
  if (!value) return "";
  const sanitizedValue = sanitizeDocument(value);
  if (sanitizedValue.length === 11) {
    return sanitizedValue.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  }
  if (sanitizedValue.length === 14) {
    return sanitizedValue.replace(
      /(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/,
      "$1.$2.$3/$4-$5"
    );
  }
  return value;
}

// ---------------- STATUS HELPER ----------------
function getFriendlyStatus(status) {
  switch (status) {
    case "pending":
      return "⏳ Aguardando início";
    case "running":
      return "⚙️ Em processamento...";
    case "finished":
      return "✅ Finalizado";
    case "error":
      return "❌ Erro na importação";
    default:
      return status || "Desconhecido";
  }
}

const statusColors = {
  pending: "#f39c12",
  running: "#3498db",
  finished: "#27ae60",
  error: "#e74c3c",
};

// ---------------- COMPONENTE ----------------
export default function Clientes() {
  const [clientes, setClientes] = useState([]);
  const [emissores, setEmissores] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [clienteSelecionado, setClienteSelecionado] = useState(null);
  const [termoBusca, setTermoBusca] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [sortConfig, setSortConfig] = useState({ key: "nome", direction: "ascending" });
  const [abaSelecionada, setAbaSelecionada] = useState("ativos");
  const [isSaving, setIsSaving] = useState(false);
  const [formData, setFormData] = useState({
    nome: "",
    documento: "",
    email: "",
    cep: "",
    logradouro: "",
    numero: "",
    complemento: "",
    bairro: "",
    cidade: "",
    estado: "",
    codigoIbge: "",
    emissores_ids: [],
  });

  const [importJob, setImportJob] = useState(localStorage.getItem("importJob") || null);
  const [importStatus, setImportStatus] = useState(null);


const fetchClients = async () => {
  try {
    const [clientesData, emissoresData] = await Promise.all([
      getClients({ incluirInativos: true }),
      getEmitters()
    ]);
    setClientes(clientesData || []);
    setEmissores(emissoresData || []);
  } catch (err) {
    console.error("Erro ao carregar clientes:", err);
  }
};

useEffect(() => {
  fetchClients();
}, [abaSelecionada]);


  useEffect(() => {
    if (!importJob) return;
    let intervalId = null;

    const checkImportStatus = async () => {
      try {
        const resp = await apiClient.get(`/clients/import/status/${importJob}`);
        const status = resp.data;
        setImportStatus(status);
        const clientsData = await getClients();
        setClientes(clientsData || []);

        if (status.status === "finished" || status.status === "error") {
          clearInterval(intervalId);
          localStorage.removeItem("importJob");
        }
      } catch (err) {
        if (err.response && err.response.status === 404) {
          clearInterval(intervalId);
          localStorage.removeItem("importJob");
          setImportJob(null);
          setImportStatus(null);
        } else {
          console.error("Erro consultando status de importação:", err);
        }
      }
    };

    checkImportStatus();
    intervalId = setInterval(checkImportStatus, 10000);
    return () => clearInterval(intervalId);
  }, [importJob]);

const processedClientes = useMemo(() => {
  let filteredData = (clientes || []).filter((cliente) => {
    if (!cliente) return false;

    // 🔹 Filtra conforme a aba
    if (abaSelecionada === "ativos" && !cliente.ativo) return false;
    if (abaSelecionada === "inativos" && cliente.ativo) return false;

    const busca = (termoBusca || "").toLowerCase();
    return (
      String(cliente.nome || "").toLowerCase().includes(busca) ||
      String(cliente.email || "").toLowerCase().includes(busca) ||
      String(cliente.cnpj || cliente.cpf || "").includes(busca)
    );
  });

  if (sortConfig.key) {
    filteredData.sort((a, b) => {
      const valA =
        sortConfig.key === "documento" ? a.cnpj || a.cpf || "" : a[sortConfig.key] || "";
      const valB =
        sortConfig.key === "documento" ? b.cnpj || b.cpf || "" : b[sortConfig.key] || "";
      const comparison = String(valA).localeCompare(String(valB), "pt-BR", { numeric: true });
      return sortConfig.direction === "ascending" ? comparison : -comparison;
    });
  }

  return filteredData;
}, [clientes, termoBusca, sortConfig, abaSelecionada]);


  const paginatedClientes = useMemo(() => {
    const indexOfLastItem = currentPage * itemsPerPage;
    const indexOfFirstItem = indexOfLastItem - itemsPerPage;
    return processedClientes.slice(indexOfFirstItem, indexOfLastItem);
  }, [currentPage, itemsPerPage, processedClientes]);

  const totalPages = Math.ceil(processedClientes.length / itemsPerPage);

  const requestSort = (key) => {
    let direction = "ascending";
    if (sortConfig.key === key && sortConfig.direction === "ascending") {
      direction = "descending";
    }
    setSortConfig({ key, direction });
    setCurrentPage(1);
  };

  const handleInputChange = async (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value ?? "" }));

    if (name === "documento") {
      const doc = sanitizeDocument(value);
      if (doc.length === 14) {
        try {
          const resp = await apiClient.get(`/clients/enrich/${doc}`);
          if (resp.status === 200 && resp.data.status === "ok") {
            const result = resp.data.data;

            setFormData((prev) => ({
              ...prev,
              nome: prev.nome || result.nome || "",
              email: prev.email || result.email || "",
              cep: prev.cep || result.cep || "",
              logradouro: prev.logradouro || result.logradouro || "",
              bairro: prev.bairro || result.bairro || "",
              cidade: prev.cidade || result.cidade || "",
              estado: prev.estado || result.estado || "",
            }));

            // ✅ Complemento ViaCEP
            let cepReceita = result.cep || result.endereco?.cep || "";
            const cleanCep = String(cepReceita).replace(/\D/g, "");
            if (cleanCep.length === 8) {
              try {
                const cepResponse = await axios.get(`https://viacep.com.br/ws/${cleanCep}/json/`);
                const cepData = cepResponse.data;
                if (!cepData.erro) {
                  setFormData((prev) => ({
                    ...prev,
                    cep: cleanCep,
                    logradouro: prev.logradouro || cepData.logradouro || "",
                    bairro: prev.bairro || cepData.bairro || "",
                    cidade: prev.cidade || cepData.localidade || "",
                    estado: prev.estado || cepData.uf || "",
                    codigoIbge: cepData.ibge || prev.codigoIbge || "",
                  }));
                }
              } catch (e) {
                console.warn("Erro ao complementar com ViaCEP:", e);
              }
            }
          }
        } catch (err) {
          console.error("Erro ao buscar ReceitaWS:", err);
        }
      }
    }
  };

  const handleCepChange = async (e) => {
    const rawCep = e.target.value;
    const cleanCep = rawCep.replace(/\D/g, "");

    setFormData((prev) => ({ ...prev, cep: cleanCep }));

    if (cleanCep.length === 8) {
      try {
        const response = await axios.get(`https://viacep.com.br/ws/${cleanCep}/json/`);
        const data = response.data;
        if (!data.erro) {
          setFormData((prev) => ({
            ...prev,
            logradouro: data.logradouro || "",
            bairro: data.bairro || "",
            cidade: data.localidade || "",
            estado: data.uf || "",
            codigoIbge: data.ibge || "",
          }));
        } else {
          console.warn("CEP não encontrado:", cleanCep);
        }
      } catch (error) {
        console.error("Erro consultando ViaCEP:", error);
      }
    }
  };

  const handleEmissorCheckbox = (e) => {
    const { value, checked } = e.target;
    setFormData((prev) => {
      const current = Array.isArray(prev.emissores_ids) ? prev.emissores_ids : [];
      if (checked) {
        if (!current.includes(value)) {
          return { ...prev, emissores_ids: [...current, value] };
        }
        return prev;
      } else {
        return { ...prev, emissores_ids: current.filter((id) => id !== value) };
      }
    });
  };

  const handleAbrirModal = (clienteParaEditar = null) => {
    setClienteSelecionado(clienteParaEditar);
    if (clienteParaEditar) {
      setFormData({
        nome: clienteParaEditar.nome || "",
        documento: clienteParaEditar.cnpj || clienteParaEditar.cpf || "",
        email: clienteParaEditar.email || "",
        cep: clienteParaEditar.cep || "",
        logradouro: clienteParaEditar.logradouro || "",
        numero: clienteParaEditar.numero || "",
        complemento: clienteParaEditar.complemento || "",
        bairro: clienteParaEditar.bairro || "",
        cidade: clienteParaEditar.cidade || "",
        estado: clienteParaEditar.estado || "",
        codigoIbge: clienteParaEditar.codigoIbge || "",
        emissores_ids: Array.isArray(clienteParaEditar.emissores_ids)
          ? clienteParaEditar.emissores_ids
          : [],
      });
    } else {
      setFormData({
        nome: "",
        documento: "",
        email: "",
        cep: "",
        logradouro: "",
        numero: "",
        complemento: "",
        bairro: "",
        cidade: "",
        estado: "",
        codigoIbge: "",
        emissores_ids: [],
      });
    }
    setShowModal(true);
  };

 const handleSalvar = async (e) => {
  e.preventDefault();
  if (isSaving) return; // evita duplo clique
  setIsSaving(true);

  if (!formData.nome || !formData.documento) {
    window.notify("Preencha Nome e CPF/CNPJ.");
    setIsSaving(false);
    return;
  }

  const doc = sanitizeDocument(formData.documento);
  let payload = {
    nome: formData.nome.trim(),
    documento: doc,
    emissores_ids: formData.emissores_ids || [],
  };

  if (formData.cep?.trim()) payload.cep = formData.cep.trim();
  if (formData.logradouro?.trim()) payload.logradouro = formData.logradouro.trim();
  if (formData.numero?.trim()) payload.numero = formData.numero.trim();
  if (formData.complemento?.trim()) payload.complemento = formData.complemento.trim();
  if (formData.bairro?.trim()) payload.bairro = formData.bairro.trim();
  if (formData.cidade?.trim()) payload.cidade = formData.cidade.trim();
  if (formData.estado?.trim()) payload.estado = formData.estado.trim();
  if (formData.codigoIbge?.trim()) payload.codigoIbge = formData.codigoIbge.trim();
  if (formData.email && formData.email.trim() !== "")
    payload.email = formData.email.trim();

  try {
    if (clienteSelecionado && clienteSelecionado._id) {
      await updateClient(clienteSelecionado._id, payload);
    } else {
      await createClient(payload);
    }

    const data = await getClients();
    setClientes(data || []);
    setShowModal(false);
  } catch (err) {
    console.error(err);

  if (err.response?.status === 409) {
    const reason = err.response.data.detail?.reason;
    if (reason === "inativo") {
      const { client_id } = err.response.data.detail;
      const confirma = await window.confirmDialog("Este cliente já existe, mas está inativo. Deseja reativá-lo?");
      if (confirma) {
        await apiClient.put(`/clients/${client_id}/reativar`);
        const data = await getClients();
        setClientes(data || []);
        window.notify("Cliente reativado com sucesso!");
        setShowModal(false);
      }
    } else if (reason === "duplicado") {
      window.notify("Esse cliente já foi cadastrado.");
    }
  } else {
    window.notify("Erro ao salvar cliente. Verifique os campos e tente novamente.");
  }
  } finally {
    setIsSaving(false);
  }
};


  const handleDelete = async (id) => {
    const confirma = await window.confirmDialog("Deseja realmente excluir este cliente?");
if (confirma) {
      try {
        await deleteClient(id);
        const data = await getClients();
        setClientes(data || []);
      } catch (err) {
        console.error(err);
        window.notify("Erro ao excluir cliente.");
      }
    }
  };

  const handleImport = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formDataUpload = new FormData();
    formDataUpload.append("file", file);
    try {
      const resp = await apiClient.post("/clients/import", formDataUpload);
      if (resp.status === 200) {
        const result = resp.data;
        setImportJob(result.job_id);
        localStorage.setItem("importJob", result.job_id);
        setImportStatus({ status: "pending" });
        window.notify("Importação iniciada. Você pode acompanhar o progresso.");
      } else {
        window.notify("Erro na importação.");
      }
    } catch (err) {
      console.error(err);
      window.notify("Falha na importação. Tente novamente.");
    } finally {
      e.target.value = "";
    }
  };

  const getNomesEmissores = (ids = []) => {
    if (!ids || ids.length === 0) return "Não vinculado";
    return ids
      .map((id) => {
        const emissor = emissores.find((e) => e._id === id);
        return emissor ? emissor.razaoSocial : "Desconhecido";
      })
      .join(", ");
  };

  // ---------- RENDERIZAÇÃO ----------
  return (
    <div className="container">
      <h1>Cadastro de Clientes</h1>

      <div style={{ marginBottom: "15px", display: "flex", gap: "10px" }}>
        <button className="btn" onClick={() => handleAbrirModal()}>
          + Incluir Cliente
        </button>
        <label className="btn">
          Importar Planilha
          <input
            type="file"
            accept=".xlsx,.csv"
            onChange={handleImport}
            style={{ display: "none" }}
          />
        </label>
        </div>

      {importStatus && (
        <div style={{ marginBottom: "15px", padding: "15px", border: "1px solid #ccc", borderRadius: "6px", backgroundColor: "#f9f9f9" }}>
          <p style={{
            margin: "0 0 10px 0",
            color: statusColors[importStatus.status] || "#555",
            fontWeight: "bold",
            fontSize: "1.1em"
          }}>
            {getFriendlyStatus(importStatus.status)}
          </p>
          <p>Processados: {(importStatus.inserted || 0) + (importStatus.skipped || 0)}</p>
          <p>Inseridos com sucesso: {importStatus.inserted || 0}</p>
          <p>Ignorados/Com erro: {importStatus.skipped || 0}</p>
          {importStatus.errors && importStatus.errors.length > 0 && (
            <details open>
              <summary style={{ fontWeight: "bold", cursor: "pointer", color: "#c0392b" }}>
                ▼ Detalhes dos Erros ({importStatus.errors.length})
              </summary>
              <table style={{ width: "100%", marginTop: "10px", borderCollapse: "collapse", fontSize: "0.9em" }}>
                <thead style={{ textAlign: "left", background: "#f2f2f2" }}>
                  <tr>
                    <th style={{ padding: "8px", border: "1px solid #ddd" }}>Linha</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd" }}>Documento (CNPJ/CPF)</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd" }}>Motivo</th>
                  </tr>
                </thead>
                <tbody>
                  {importStatus.errors.map((err, i) => (
                    <tr key={i}>
                      <td style={{ padding: "8px", border: "1px solid #ddd" }}>{err.linha || "-"}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd" }}>{err.documento ? formatCnpjCpf(err.documento) : "Não informado"}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", color: "#555" }}>{translateErrorMessage(err.erro)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      )}
  {/* Checkbox para alternar entre ativos e inativos */}
  <div className="checkbox-filter">
    <input
      type="checkbox"
      checked={abaSelecionada === 'inativos'}
      onChange={() => setAbaSelecionada(abaSelecionada === 'ativos' ? 'inativos' : 'ativos')}
    />
    <span>
      Mostrar inativos
    </span>
  </div>
      <div className="search-container">
        <input
          type="text"
          placeholder="Pesquisar por nome, documento, e-mail..."
          className="search-input"
          value={termoBusca}
          onChange={(e) => { setTermoBusca(e.target.value); setCurrentPage(1); }}
        />
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th onClick={() => requestSort('nome')} className="sortable-header">
              Nome {sortConfig.key === 'nome' && (sortConfig.direction === 'ascending' ? '▲' : '▼')}
            </th>
            <th onClick={() => requestSort('documento')} className="sortable-header">
              CNPJ/CPF {sortConfig.key === 'documento' && (sortConfig.direction === 'ascending' ? '▲' : '▼')}
            </th>
            <th onClick={() => requestSort('email')} className="sortable-header">
              Email {sortConfig.key === 'email' && (sortConfig.direction === 'ascending' ? '▲' : '▼')}
            </th>
            <th className="col-texto-longo">Emissores Vinculados</th>
            <th>Ações</th>
          </tr>
        </thead>
        <tbody>
          {paginatedClientes.map((c) => (
            <tr key={c._id} className={!c.ativo ? "inativo" : ""}>
              <td>{c.nome}{!c.ativo && " (Inativo)"}</td>
              <td>{formatCnpjCpf(c.cnpj || c.cpf)}</td>
              <td>{c.email || "-"}</td>
              <td className="col-texto-longo" title={getNomesEmissores(c.emissores_ids)}>
                <div>{getNomesEmissores(c.emissores_ids)}</div>
              </td>
              <td>
              {c.ativo ? (
                <>
                  <button className="btn-link" onClick={() => handleAbrirModal(c)}>Editar</button>{" "}
                  |{" "}
                  <button className="btn-link delete" onClick={() => handleDelete(c._id)}>Excluir</button>
                </>
              ) : (
                <button
                  className="btn-link reativar"
                  onClick={async () => {
                    const confirma = await window.confirmDialog(`Deseja reativar ${c.nome}?`);
                    if (confirma) {
                      try {
                        await apiClient.put(`/clients/${c._id}/reativar`);
                        const data = await getClients({ incluirInativos: true });
                        setClientes(data || []);
                        window.notify("Cliente reativado com sucesso!");
                      } catch (error) {
                        console.error(error);
                        window.notify("Erro ao reativar cliente.");
                      }
                    }
                  }}
                >
                  Reativar
                </button>
              )}
            </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="pagination-controls">
        <div>
          <label htmlFor="itemsPerPage">Itens por página: </label>
          <select
            id="itemsPerPage"
            value={itemsPerPage}
            onChange={(e) => { setItemsPerPage(Number(e.target.value)); setCurrentPage(1); }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
        <span>
          Página {currentPage} de {totalPages || 1} ({processedClientes.length} clientes)
        </span>
        <div>
          <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage === 1}>Anterior</button>
          <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages || totalPages === 0}>Próximo</button>
        </div>
      </div>

      {showModal && (
        <div className="modal-overlay">
          <div className="modal">
            <button className="modal-close" onClick={() => setShowModal(false)}>&times;</button>
            <h2>{clienteSelecionado ? "Editar Cliente" : "Novo Cliente"}</h2>
            <form onSubmit={handleSalvar}>
              <div className="form-grid">
                <label className="full-width-grid-item">
                  CPF/CNPJ:
                  <input type="text" name="documento" value={formatCnpjCpf(formData.documento)} onChange={handleInputChange} />
                </label>
                <label>
                  Nome/Razão Social:
                  <input type="text" name="nome" value={formData.nome} onChange={handleInputChange} />
                </label>
                <label>
                  Email:
                  <input type="email" name="email" value={formData.email} onChange={handleInputChange} />
                </label>
              </div>

              <div className="form-group">
                <label>Vincular aos Emissores:</label>
                <div className="emissores-grid">
                  {emissores.map((e) => (
                    <label key={e._id} className={`emissor-card ${formData.emissores_ids.includes(e._id) ? "selected" : ""}`}>
                      <input
                        type="checkbox"
                        value={e._id}
                        checked={formData.emissores_ids.includes(e._id)}
                        onChange={handleEmissorCheckbox}
                      />
                      <div className="emissor-info">
                        <span className="emissor-razao">{e.razaoSocial}</span>
                        <span className="emissor-cnpj">{formatCnpjCpf(e.cnpj)}</span>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <h3 style={{ marginTop: "20px" }}>Endereço</h3>
              <div className="form-grid">
                <label>
                  CEP:
                  <input type="text" name="cep" value={formData.cep} onChange={handleCepChange} />
                </label>
                <label>
                  Logradouro:
                  <input type="text" name="logradouro" value={formData.logradouro} onChange={handleInputChange} />
                </label>
                <label>
                  Número:
                  <input type="text" name="numero" value={formData.numero} onChange={handleInputChange} />
                </label>
                <label>
                  Complemento:
                  <input type="text" name="complemento" placeholder="Opcional" value={formData.complemento} onChange={handleInputChange} />
                </label>
                <label>
                  Bairro:
                  <input type="text" name="bairro" value={formData.bairro} onChange={handleInputChange} />
                </label>
                <label>
                  Cidade:
                  <input type="text" name="cidade" value={formData.cidade} onChange={handleInputChange} />
                </label>
                <label>
                  Estado:
                  <input type="text" name="estado" value={formData.estado} onChange={handleInputChange} />
                </label>
                <label>
                  Cód. Município:
                  <input type="text" name="codigoIbge" value={formData.codigoIbge} onChange={handleInputChange} readOnly />
                </label>
              </div>

              <div className="modal-actions">
                <button type="submit" className="btn">Salvar</button>
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancelar</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}