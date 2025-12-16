import { useEffect, useState, useMemo, useRef, useCallback } from "react";
import {
  CircleCheck,
  CircleX,
  Clock10,
  Search,
  Download,
  Code,
  MoreVertical,
  AlertTriangle,
  ShieldX,
  Loader2,
} from "lucide-react";
import {
  getTasks,
  getResumo,
  getClientStats,
  downloadAllXml,
  downloadGuia,
  downloadXml,
  downloadAllPdf,
  getClientsUpdatedRecently, // Importado e agora usado
  clearRecentClientUpdates, // Importado e agora usado
  deleteTask,
  cancelTask,
  cancelTasksBatch,
  exportTasksXlsx
} from "../services/api";
import "../styles/Dashboard.css";

export default function Dashboard() {
  const [tasks, setTasks] = useState([]);
  const [resumo, setResumo] = useState([]);
  const [mes, setMes] = useState(new Date().getMonth() + 1);
  const [ano, setAno] = useState(new Date().getFullYear());
  const [searchTerm, setSearchTerm] = useState("");
  const [filtroEmissor, setFiltroEmissor] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(25);
  const [filtroStatus, setFiltroStatus] = useState("");
  const [clientStats, setClientStats] = useState({ total: 0, ativos: 0, inativos: 0 });
  const [isDownloadingBatch, setIsDownloadingBatch] = useState(false);

  // Modais de Ação
  const [isErrorModalOpen, setIsErrorModalOpen] = useState(false);
  const [modalErrorMessage, setModalErrorMessage] = useState("");
  const [errorModalTaskId, setErrorModalTaskId] = useState(null);

  const [isCancelModalOpen, setIsCancelModalOpen] = useState(false); // Modal Individual
  const [currentTaskToCancel, setCurrentTaskToCancel] = useState(null);
  const [justificativa, setJustificativa] = useState("");
  const [isCanceling, setIsCanceling] = useState(false);
  const [motivo, setMotivo] = useState("2");

  const [isCancelBatchModalOpen, setIsCancelBatchModalOpen] = useState(false); // Modal Lote
  const [justificativaLote, setJustificativaLote] = useState("");
  const [isCancelingLote, setIsCancelingLote] = useState(false);
  const [motivoLote, setMotivoLote] = useState("2");

  // --- NOVO: Modal de Clientes Atualizados ---
  const [isUpdatesModalOpen, setIsUpdatesModalOpen] = useState(false);
  const [updatedClientsList, setUpdatedClientsList] = useState([]);


  // Estados de UI
  const [openMenuId, setOpenMenuId] = useState(null);
  const [selectedTaskIds, setSelectedTaskIds] = useState([]); // Para lote
  const menuRef = useRef(null);
  const batchMenuRef = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const [tasksRes, resumoRes, clientsStatsRes] = await Promise.all([
        getTasks({ mes, ano }),
        getResumo(mes, ano),
        getClientStats(),
      ]);
      setTasks(tasksRes);
      setResumo(resumoRes);
      setClientStats(clientsStatsRes);
    } catch (err) {
      console.error("Erro ao carregar dados:", err);
    }
  }, [mes, ano]);

  useEffect(() => {
    fetchData();
    const intervalId = setInterval(fetchData, 30000);
    return () => clearInterval(intervalId);
  }, [fetchData]);

  useEffect(() => {
    function onDocClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        if (openMenuId !== "batch") setOpenMenuId(null);
      }
      if (batchMenuRef.current && !batchMenuRef.current.contains(e.target)) {
        if (openMenuId === "batch") setOpenMenuId(null);
      }
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [openMenuId]);

  // Limpa a seleção de lote ao mudar de página ou filtro
  useEffect(() => {
    setSelectedTaskIds([]);
  }, [currentPage, itemsPerPage, filtroStatus]);

  const notasPorStatus = tasks.reduce(
    (acc, task) => {
      const st = (task.status || "").toLowerCase();
      if (st === "accepted") acc.sucesso++;
      else if (st === "pending") acc.pending++;
      else if (st === "error") acc.erro++;
      else if (st === "canceled") acc.cancelado++;
      return acc;
    },
    { sucesso: 0, pending: 0, erro: 0, cancelado: 0 }
  );

  const filteredTasks = useMemo(() =>
    tasks
      .filter((t) => (t.cliente_nome || "").toLowerCase().includes(searchTerm.toLowerCase()))
      .filter((t) => (filtroEmissor ? t.emissor_nome === filtroEmissor : true))
      .filter((t) => (filtroStatus ? (t.status || "").toLowerCase() === filtroStatus : true)),
  [tasks, searchTerm, filtroEmissor, filtroStatus]
  );

  const totalPages = Math.ceil(filteredTasks.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const currentTasks = filteredTasks.slice(startIndex, startIndex + itemsPerPage);

  const emissoresUnicos = [...new Set(tasks.map((t) => t.emissor_nome).filter(Boolean))];

  // Labels de Status
  const statusLabels = {
    accepted: "Emitida",
    pending: "Pendente",
    error: "Erro",
    canceled: "Cancelada",
  };

  // --- Funções de Download (Lote) ---
  const handleDownloadFiltered = async () => {
    if (filteredTasks.length === 0) {
      window.notify("Nenhuma nota encontrada.", "error");
      return;
    }
    setIsDownloadingBatch(true);
    setOpenMenuId(null);
    window.notify("Gerando ZIP de XMLs... O download iniciará em instantes.", "info");

    const emitterId = filtroEmissor ? filteredTasks[0]?.emitter_id : undefined;
    try {
      await downloadAllXml({ emitterId, mes, ano });
      window.notify("Download de XML iniciado.", "success");
    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro ao baixar XML.";
      window.notify(msg, "error");
    } finally {
      setIsDownloadingBatch(false);
    }
  };

const handleDownloadFilteredPDF = async () => {
    if (filteredTasks.length === 0) {
      window.notify("Nenhuma nota encontrada.", "error");
      return;
    }
    setIsDownloadingBatch(true);
    setOpenMenuId(null);
    window.notify("Compilando PDFs e gerando ZIP... Aguarde.", "info");
    const emitterId = filtroEmissor ? filteredTasks[0]?.emitter_id : undefined;
    try {
      await downloadAllPdf({ emitterId, mes, ano });
      window.notify("Download de PDFs iniciado.", "success");
    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro ao baixar PDFs.";
      window.notify(msg, "error");
    } finally {
      setIsDownloadingBatch(false);
    }
  };

  // --- Funções de Download (Individual) ---
  async function handleDownloadGuia(taskId) {
    try {
      await downloadGuia(taskId);
    } catch (err) {
      const msg = err?.response?.data?.detail || "Guia oficial ainda não disponível.";
      alert(msg);
      fetchData();
    }
  }

  // --- Funções de Modal (Erro) ---
  const handleShowError = (task) => {
    let message = "Não foi possível detalhar o erro.";
    try {
      const rawResponse = task.transmit?.raw_response;
      if (rawResponse) {
        const parsed = JSON.parse(rawResponse);
        if (parsed.erros && parsed.erros[0] && parsed.erros[0].Descricao) {
          message = `(${parsed.erros[0].Codigo}) ${parsed.erros[0].Descricao}`;
        }
      }
      if (message === "Não foi possível detalhar o erro.") {
          const receiptError = task.transmit?.receipt?.erros?.[0];
          if (receiptError) {
            message = receiptError;
          }
      }
    } catch (e) {
      console.error("Falha ao analisar JSON de erro:", e);
      message = task.transmit?.receipt?.erros?.[0] || message;
    }
    setModalErrorMessage(message);
    setErrorModalTaskId(task._id);
    setIsErrorModalOpen(true);
  };

  const handleResolveError = async () => {
    if (!errorModalTaskId) return;
    try {
      await deleteTask(errorModalTaskId);
      window.notify("Task de erro marcada como resolvida.", "success");
      setIsErrorModalOpen(false);
      setErrorModalTaskId(null);
      fetchData();
    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro ao descartar a task.";
      window.notify(msg, "error");
    }
  };

  // --- Funções de Modal (Cancelamento Individual) ---
  const openCancelModal = (task) => {
    setCurrentTaskToCancel(task);
    setJustificativa("");
    setIsCancelModalOpen(true);
    setOpenMenuId(null);
  };

  const closeCancelModal = () => {
    if (isCanceling) return;
    setIsCancelModalOpen(false);
    setCurrentTaskToCancel(null);
    setJustificativa("");
  };

  const handleConfirmCancel = async () => {
    if (justificativa.length < 15) {
      window.notify("A justificativa deve ter pelo menos 15 caracteres.", "error");
      return;
    }
    if (!currentTaskToCancel) return;

    setIsCanceling(true);
    try {
      await cancelTask(currentTaskToCancel._id, justificativa, motivo);
      window.notify("Nota cancelada com sucesso!", "success");
      closeCancelModal();
      fetchData();
    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro desconhecido ao cancelar.";
      window.notify(msg, "error");
    } finally {
      setIsCanceling(false);
    }
  };

  // --- Funções de Modal (Cancelamento em Lote) ---
  const handleSelectTask = (taskId, isSelected) => {
    setSelectedTaskIds(prev =>
      isSelected
        ? [...prev, taskId]
        : prev.filter(id => id !== taskId)
    );
  };

  const handleSelectAll = (e) => {
    if (e.target.checked) {
      const acceptedIds = currentTasks
        .filter(t => (t.status || "").toLowerCase() === "accepted")
        .map(t => t._id);
      setSelectedTaskIds(acceptedIds);
    } else {
      setSelectedTaskIds([]);
    }
  };

  const handleConfirmCancelBatch = async () => {
    if (justificativaLote.length < 15) {
      window.notify("A justificativa deve ter pelo menos 15 caracteres.", "error");
      return;
    }
    if (selectedTaskIds.length === 0) return;

    setIsCancelingLote(true);
    try {
      const result = await cancelTasksBatch({
        task_ids: selectedTaskIds,
        justificativa: justificativaLote,
        cMotivo: motivoLote
      });

      const { sucessos, falhas } = result;

      if (sucessos > 0) {
        window.notify(`${sucessos} nota(s) cancelada(s) com sucesso.`, "success");
      }
      if (falhas > 0) {
        window.notify(`${falhas} nota(s) falharam ao cancelar. Verifique o status.`, "error");
      }

      setIsCancelBatchModalOpen(false);
      setJustificativaLote("");
      setSelectedTaskIds([]);
      fetchData();

    } catch (err) {
      const msg = err?.response?.data?.detail || "Erro desconhecido ao cancelar em lote.";
      window.notify(msg, "error");
    } finally {
      setIsCancelingLote(false);
    }
  };

  // --- NOVO: Funções para Mostrar Detalhes de Atualização ---
  const handleShowRecentUpdates = async () => {
    if (clientStats.atualizados === 0) return;

    try {
      const data = await getClientsUpdatedRecently();
      setUpdatedClientsList(data);
      setIsUpdatesModalOpen(true);
    } catch (err) {
      console.error(err);
      window.notify("Erro ao buscar detalhes das atualizações.", "error");
    }
  };

  const handleClearUpdates = async () => {
    try {
      await clearRecentClientUpdates();
      setIsUpdatesModalOpen(false);
      fetchData(); // Atualiza os contadores
      window.notify("Lista de atualizações limpa.", "success");
    } catch (err) {
      console.error(err);
      window.notify("Erro ao limpar lista.", "error");
    }
  };


  // --- Funções de Formatação ---
  function formatDateTimeBR(isoDate) {
    if (!isoDate) return "-";
    let dateStr = isoDate;
    const hasTimezone = isoDate.endsWith('Z') || isoDate.includes('+') || isoDate.lastIndexOf('-') > 10;
    if (!hasTimezone) dateStr = isoDate + 'Z';
    const date = new Date(dateStr);
    return date.toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  }

  // --- Renderização ---
  return (
    <div className="container">
      <h1>Dashboard</h1>

      {/* Filtros de Mês/Ano */}
      <div className="filtros-container">
        <label htmlFor="mes-select">Mês:</label>
        <select id="mes-select" className="filtro-input" value={mes} onChange={(e) => setMes(parseInt(e.target.value))}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
            <option key={m} value={m}>{m.toString().padStart(2, "0")}</option>
          ))}
        </select>
        <label htmlFor="ano-input">Ano:</label>
        <select
          id="ano-input"
          className="filtro-input"
          value={ano}
          onChange={(e) => setAno(parseInt(e.target.value))}
        >
          {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i).map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </div>
      <button
        className="btn btn-success"
          onClick={() => exportTasksXlsx({ mes, ano })}
        >
          Exportar Excel
      </button>

      <h3>Resumo de Notas Fiscais</h3>

      {/* Cards */}
      <div className="dashboard-grid">
        <div
          className="dashboard-card card-pendente"
          onClick={() => { setFiltroStatus("pending"); setCurrentPage(1); }}
          style={{ cursor: "pointer" }}
        >
          <div>
            <div className="card-title"><Clock10 size={20} color="#e0c51a" strokeWidth={1.5}/>Pendentes</div>
            <div className="card-value">{notasPorStatus.pending}</div>
          </div>
        </div>
        <div
          className="dashboard-card card-erro"
          onClick={() => { setFiltroStatus("error"); setCurrentPage(1); }}
          style={{ cursor: "pointer" }}
        >
          <div>
            <div className="card-title"><CircleX size={20} color="#d82222" strokeWidth={1.5}/>Com Erro</div>
            <div className="card-value">{notasPorStatus.erro}</div>
          </div>
        </div>
        <div
          className="dashboard-card card-sucesso"
          onClick={() => { setFiltroStatus("accepted"); setCurrentPage(1); }}
          style={{ cursor: "pointer" }}
        >
          <div>
            <div className="card-title"><CircleCheck size={20} color="#6bb39b" strokeWidth={1.5}/>Emitidas com Sucesso</div>
            <div className="card-value">{notasPorStatus.sucesso}</div>
          </div>
        </div>
         <div // Card de Canceladas
          className="dashboard-card card-cancelada"
          onClick={() => { setFiltroStatus("canceled"); setCurrentPage(1); }}
          style={{ cursor: "pointer" }}
        >
          <div>
            <div className="card-title"><ShieldX size={20} color="#888" strokeWidth={1.5}/>Canceladas</div>
            <div className="card-value">{notasPorStatus.cancelado}</div>
          </div>
        </div>
      </div>

      {/* Resumo Clientes */}
      <h3 style={{ marginTop: "40px", marginBottom: "10px" }}>Resumo de Clientes</h3>
      <div style={{
        display: "flex",
        gap: "30px",
        fontSize: "14px",
        opacity: 0.85,
        marginBottom: "30px"
      }}>
        <span>Total: <strong>{clientStats.total}</strong></span>
        <span>Ativos: <strong style={{ color: "#2d8f65" }}>{clientStats.ativos}</strong></span>
        <span>Inativos: <strong style={{ color: "#c44747" }}>{clientStats.inativos}</strong></span>

        {/* MODIFICADO AQUI: onClick chama função do modal */}
        <span
            onClick={handleShowRecentUpdates}
            style={{
              cursor: clientStats.atualizados > 0 ? "pointer" : "default",
            }}
          >
            Atualizados recentemente:{" "}
            <strong style={{ color: clientStats.atualizados > 0 ? "#d88a2a" : "#777" }}>
              {clientStats.atualizados}
            </strong>
        </span>
      </div>

      {/* Totais por Emissor */}
      <h3 style={{ marginTop: "40px" }}>Totais por Emissor</h3>
      <table className="data-table">
        <thead><tr><th>Emissor</th><th>Total de Notas</th><th>Valor Total (R$)</th></tr></thead>
        <tbody>
          {resumo.length > 0 ? resumo.map((r) => (
            <tr key={r._id}>
              <td>{r.emissor_nome || "-"}</td>
              <td>{r.total_notas}</td>
              <td>{r.valor_total?.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</td>
            </tr>
          )) : (
            <tr><td colSpan={3} style={{ textAlign: "center" }}>Nenhum dado disponível</td></tr>
          )}
        </tbody>
      </table>

      {/* Notas Recentes + botões de lote */}
      <div className="table-header-controls">
        <h3 style={{ marginTop: "40px", marginBottom: "15px" }}>Notas Recentes</h3>
        <div className="table-header-controls" style={{ display: "flex", gap: "10px" }}>

          <button
            className="btn dashboard-action-btn btn-danger"
            onClick={() => setIsCancelBatchModalOpen(true)}
            disabled={selectedTaskIds.length === 0}
          >
            <ShieldX size={16}/> Cancelar {selectedTaskIds.length > 0 ? `(${selectedTaskIds.length})` : 'em lote'}
          </button>

          <div style={{ position: "relative" }} ref={batchMenuRef}>
            <button
              className="btn dashboard-action-btn"
              onClick={(e) => {
                e.stopPropagation();
                setOpenMenuId(openMenuId === "batch" ? null : "batch");
              }}
              disabled={filteredTasks.length === 0}
            >
              <Download size={16}/> Baixar em lote
            </button>

            {openMenuId === "batch" && (
              <div className="action-menu" style={{ right: 0 }}>
                <button className="action-item" onClick={handleDownloadFiltered}>
                  <Code size={16}/> XML (ZIP)
                </button>
                <button className="action-item" onClick={handleDownloadFilteredPDF}>
                  <span className="pdf-chip">PDF</span> DANFS-e (ZIP)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Busca + filtro emissor */}
      <div className="table-filters-container">
        <div className="search-wrapper">
          <Search size={18} className="search-icon" />
          <input
            type="text"
            placeholder="Buscar por nome do cliente..."
            className="table-search-input"
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setCurrentPage(1); }}
          />
        </div>
        <select
          className="table-filter-select"
          value={filtroEmissor}
          onChange={(e) => { setFiltroEmissor(e.target.value); setCurrentPage(1); }}
        >
          <option value="">Todos os Emissores</option>
          {emissoresUnicos.map((emissor) => (<option key={emissor} value={emissor}>{emissor}</option>))}
        </select>
      </div>

      {filtroStatus && (
        <button
          className="btn dashboard-action-btn"
          style={{ marginBottom: "15px" }}
          onClick={() => setFiltroStatus("")}
        >
          Limpar Filtro: {statusLabels[filtroStatus] || filtroStatus}
        </button>
      )}

      {/* Tabela */}
      <table className="data-table">
        <thead>
          <tr>
            <th style={{ width: 40, textAlign: "center" }}>
              <input
                type="checkbox"
                title="Selecionar todas as notas 'Emitidas' desta página"
                onChange={handleSelectAll}
                checked={
                  currentTasks.filter(t => (t.status || "").toLowerCase() === "accepted").length > 0 &&
                  currentTasks
                    .filter(t => (t.status || "").toLowerCase() === "accepted")
                    .every(t => selectedTaskIds.includes(t._id))
                }
              />
            </th>
            <th>Cliente</th>
            <th>Emissor</th>
            <th>Data de Envio</th>
            <th>Status</th>
            <th style={{ width: 60, textAlign: "center" }}>Ações</th>
          </tr>
        </thead>
        <tbody>
          {currentTasks.length > 0 ? currentTasks.map((t) => {
            const status = (t.status || "").toLowerCase();
            const isAccepted = status === "accepted";
            const isCanceled = status === "canceled";
            const isSelected = selectedTaskIds.includes(t._id);

            return (
              <tr key={t._id} className={isSelected ? 'row-selected' : ''}>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    disabled={!isAccepted}
                    checked={isSelected}
                    onChange={(e) => handleSelectTask(t._id, e.target.checked)}
                  />
                </td>
                <td>{t.cliente_nome || "-"}</td>
                <td>{t.emissor_nome || "-"}</td>
                <td>{formatDateTimeBR(t.created_at)}</td>
                <td>
                  <span
                    className={`status status-${status}`}
                    onClick={() => status === 'error' && handleShowError(t)}
                    style={{ cursor: status === 'error' ? 'pointer' : 'default' }}
                    title={status === 'error' ? 'Clique para ver o erro' : ''}
                  >
                    {statusLabels[status] || t.status}
                  </span>
                </td>
                <td style={{ textAlign: "center", position: "relative" }}>
                  {isAccepted ? (
                    <>
                      <button className="icon-btn" onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === t._id ? null : t._id); }}>
                        <MoreVertical size={18} />
                      </button>

                      {openMenuId === t._id && (
                          <div className="action-menu" ref={menuRef}>
                            <button className="action-item" onClick={() => downloadXml(t._id)}>
                              <Code size={16}/> Download XML
                            </button>

                            {t.has_pdf ? (
                              <button className="action-item" onClick={() => handleDownloadGuia(t._id)}>
                                <span className="pdf-chip">PDF</span> Download DANFS-e
                              </button>
                            ) : (
                              <div className="action-item disabled-tip" title="Guia ainda não disponível">DANFS-e indisponível</div>
                            )}

                            <div className="action-divider" />
                            <button
                              className="action-item action-item-danger"
                              onClick={() => openCancelModal(t)}
                            >
                              <AlertTriangle size={16}/> Cancelar Nota
                            </button>
                          </div>
                      )}
                    </>
                  ) : (
                    <span style={{ color: "#999", fontSize: 12 }}>{isCanceled ? "N/A" : "?"}</span>
                  )}
                </td>
              </tr>
            );
          }) : (
            <tr><td colSpan={6} style={{ textAlign: "center" }}>Nenhuma nota encontrada.</td></tr>
          )}
        </tbody>
      </table>

      {/* Paginação */}
      {filteredTasks.length > 0 && (
        <div className="pagination-controls">
          <div>
            <label htmlFor="itemsPerPage">Itens por página: </label>
            <select id="itemsPerPage" value={itemsPerPage} onChange={(e) => { setItemsPerPage(Number(e.target.value)); setCurrentPage(1); }}>
              <option value={25}>25</option><option value={50}>50</option><option value={100}>100</option>
            </select>
          </div>
          <span> Página {currentPage} de {totalPages || 1} ({filteredTasks.length} notas) </span>
          <div>
            <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage === 1}>Anterior</button>
            <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages || totalPages === 0}>Próxima</button>
          </div>
        </div>
      )}

      {/* --- MODAIS --- */}

      {/* Modal de Erro */}
      {isErrorModalOpen && (
        <div className="modal-overlay">
          <div className="modal">
            <button className="modal-close" onClick={() => setIsErrorModalOpen(false)}>&times;</button>
            <h3 style={{ marginTop: 0 }}>Detalhes do Erro da Nota</h3>
            <p style={{
              whiteSpace: "pre-wrap", wordBreak: "break-word", background: "#f7f7f7",
              border: "1px solid #ddd", padding: "10px", borderRadius: "4px"
            }}>
              {modalErrorMessage}
            </p>
            <div className="modal-actions" style={{ justifyContent: "flex-end", marginTop: "20px" }}>
              <button
                className="btn btn-secondary"
                onClick={handleResolveError}
                style={{ marginRight: "10px" }}
              >
                Marcar como Resolvido
              </button>
              <button className="btn" onClick={() => setIsErrorModalOpen(false)}>
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Cancelamento Individual */}
      {isCancelModalOpen && (
        <div className="modal-overlay">
          <div className="modal">
            <button className="modal-close" onClick={closeCancelModal} disabled={isCanceling}>&times;</button>
            <h3 style={{ marginTop: 0 }}>Cancelar Nota Fiscal</h3>

            {currentTaskToCancel && (
              <p style={{ fontSize: '14px', background: '#f9f9f9', padding: '10px', borderRadius: '4px' }}>
                Nota N°: <strong>{currentTaskToCancel.transmit?.receipt?.numero_nfse || currentTaskToCancel._id}</strong>
                <br/>
                Cliente: <strong>{currentTaskToCancel.cliente_nome}</strong>
                <br/>
                Valor: <strong>{currentTaskToCancel.valor?.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</strong>
              </p>
            )}
            {/* Motivo do Cancelamento */}
            <label
              htmlFor="motivo"
              style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}
            >
              Motivo do Cancelamento
            </label>

            <select
              id="motivo"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              style={{ width: '100%', padding: '8px', marginBottom: '15px', borderRadius: '4px', borderColor: '#ccc' }}
            >
              <option value="1">Erro na emissão</option>
              <option value="2">Serviço não prestado</option>
              <option value="9">Outros</option>
            </select>

            <label htmlFor="justificativa" style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
              Justificativa (mín. 15 caracteres)
            </label>
            <textarea
              id="justificativa"
              rows={4}
              value={justificativa}
              onChange={(e) => setJustificativa(e.target.value)}
              placeholder="Ex: Erro na emissão dos valores, serviço não prestado..."
              style={{ width: '100%', padding: '8px', boxSizing: 'border-box', borderRadius: '4px', borderColor: '#ccc' }}
            />

            <div className="modal-actions" style={{ justifyContent: "flex-end", marginTop: "20px" }}>
              <button
                className="btn btn-secondary"
                onClick={closeCancelModal}
                style={{ marginRight: "10px" }}
                disabled={isCanceling}
              >
                Fechar
              </button>
              <button
                className="btn btn-danger"
                onClick={handleConfirmCancel}
                disabled={justificativa.length < 15 || isCanceling}
              >
                {isCanceling ? "Cancelando..." : "Confirmar Cancelamento"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Cancelamento em Lote */}
      {isCancelBatchModalOpen && (
        <div className="modal-overlay">
          <div className="modal">
            <button className="modal-close" onClick={() => setIsCancelBatchModalOpen(false)} disabled={isCancelingLote}>&times;</button>
            <h3 style={{ marginTop: 0 }}>Cancelar Notas em Lote</h3>

            <p>Você está prestes a cancelar <strong>{selectedTaskIds.length} nota(s) fiscal(is)</strong>. Esta ação é irreversível.</p>

            {/* Motivo do Cancelamento */}
            <label
              htmlFor="motivoLote"
              style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}
            >
              Motivo do Cancelamento
            </label>

            <select
              id="motivoLote"
              value={motivoLote}
              onChange={(e) => setMotivoLote(e.target.value)}
              style={{ width: '100%', padding: '8px', marginBottom: '15px', borderRadius: '4px', borderColor: '#ccc' }}
            >
              <option value="1">Erro na emissão</option>
              <option value="2">Serviço não prestado</option>
              <option value="9">Outros</option>
            </select>


            <label htmlFor="justificativaLote" style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
              Justificativa Única (mín. 15 caracteres)
            </label>
            <textarea
              id="justificativaLote"
              rows={4}
              value={justificativaLote}
              onChange={(e) => setJustificativaLote(e.target.value)}
              placeholder="Ex: Erro na emissão dos valores, serviço não prestado..."
              style={{ width: '100%', padding: '8px', boxSizing: 'border-box', borderRadius: '4px', borderColor: '#ccc' }}
            />

            <div className="modal-actions" style={{ justifyContent: "flex-end", marginTop: "20px" }}>
              <button
                className="btn btn-secondary"
                onClick={() => setIsCancelBatchModalOpen(false)}
                style={{ marginRight: "10px" }}
                disabled={isCancelingLote}
              >
                Fechar
              </button>
              <button
                className="btn btn-danger"
                onClick={handleConfirmCancelBatch}
                disabled={justificativaLote.length < 15 || isCancelingLote}
              >
                {isCancelingLote ? `Cancelando...` : `Confirmar Cancelamento (${selectedTaskIds.length})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* --- NOVO MODAL: Clientes Atualizados Recentemente --- */}
      {isUpdatesModalOpen && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: "800px", width: "90%" }}>
            <button className="modal-close" onClick={() => setIsUpdatesModalOpen(false)}>&times;</button>

            <h3 style={{ marginTop: 0 }}>Clientes Atualizados Recentemente</h3>
            <p style={{ fontSize: "14px", color: "#666" }}>
              O sistema detectou alterações na Receita Federal para estes clientes e atualizou os dados automaticamente.
            </p>

            <div style={{ maxHeight: "400px", overflowY: "auto", marginTop: "15px", border: "1px solid #eee" }}>
              <table className="data-table" style={{ marginTop: 0 }}>
                <thead style={{ position: "sticky", top: 0, zIndex: 1, background: "#f9f9f9" }}>
                  <tr>
                    <th>Cliente</th>
                    <th>Documento</th>
                    <th>Campos Alterados</th>
                  </tr>
                </thead>
                <tbody>
                  {updatedClientsList.length > 0 ? (
                    updatedClientsList.map((cli, idx) => (
                      <tr key={idx}>
                        <td>{cli.nome || "Sem nome"}</td>
                        <td>{cli.cnpj || cli.cpf || "-"}</td>
                        <td>
                          <div style={{ display: "flex", gap: "5px", flexWrap: "wrap" }}>
                            {cli.campos_atualizados && cli.campos_atualizados.map((campo) => (
                              <span key={campo} style={{
                                background: "#fff3cd", color: "#856404",
                                padding: "2px 6px", borderRadius: "4px", fontSize: "12px", border: "1px solid #ffeeba"
                              }}>
                                {campo}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan="3" style={{textAlign: "center"}}>Nenhum detalhe disponível.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="modal-actions" style={{ justifyContent: "space-between", marginTop: "20px" }}>
              <button
                className="btn btn-secondary"
                onClick={handleClearUpdates}
                title="Remove o aviso de atualização e zera o contador"
              >
                <CircleCheck size={16} style={{marginRight: 5}}/>
                Marcar todos como vistos
              </button>

              <button className="btn" onClick={() => setIsUpdatesModalOpen(false)}>
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}