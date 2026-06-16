import { useState, useEffect } from "react";
import { getEmitters, processarPGDAS, getAliquotasAtuais } from "../services/api";
import "../styles/App.css";

export default function Aliquota() {
  const [emissores, setEmissores] = useState([]);
  const [emitterId, setEmitterId] = useState("");
  const [file, setFile] = useState(null);
  const [resultado, setResultado] = useState(null); // Armazena o resultado do cálculo atual
  const [aliquotas, setAliquotas] = useState([]);   // Armazena o histórico do banco
  const [loading, setLoading] = useState(false);

  // Estados dos Filtros
  const hoje = new Date();
  const [filtroMes, setFiltroMes] = useState(String(hoje.getMonth() + 1));
  const [filtroAno, setFiltroAno] = useState(String(hoje.getFullYear()));

  // 🔹 Carregar dados iniciais
  useEffect(() => {
    async function loadData() {
      try {
        const emissoresData = await getEmitters();
        setEmissores(emissoresData || []);
        const aliqs = await getAliquotasAtuais();
        setAliquotas(aliqs || []);
      } catch (error) {
        console.error("Erro ao carregar dados:", error);
      }
    }
    loadData();
  }, []);

  // 🔹 Lógica de Filtragem (CORRIGIDA: Converte tipos para garantir match)
  const aliquotasFiltradas = aliquotas.filter(a => {
    const mesDb = String(a.mes); // Banco: 9 -> "9"
    const anoDb = String(a.ano); // Banco: 2025 -> "2025"

    const mesMatch = filtroMes ? mesDb === filtroMes : true;
    const anoMatch = filtroAno ? anoDb === filtroAno : true;

    return mesMatch && anoMatch;
  });

  // 🔹 Opções para os Selects de Filtro (Ordenados numericamente)
  // Cria um Set para não repetir valores, converte para array e ordena
  const mesesOpcoes = [...new Set(aliquotas.map(a => a.mes))].sort((a, b) => a - b);
  const anosOpcoes = [...new Set(aliquotas.map(a => a.ano))].sort((a, b) => a - b);

  // 🔹 Formatadores Visuais
  const formatMoney = (val) => {
    if (val === undefined || val === null) return "R$ 0,00";
    return val.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  };

  const formatPercent = (val) => {
    if (val === undefined || val === null) return "0,00%";
    // Ex: 0.116248 -> 11.6248 -> "11,62%"
    return (val * 100).toFixed(2).replace('.', ',') + "%";
  };

  // 🔹 Processar PGDAS
  async function handleProcessar(e) {
      e.preventDefault();
      if (!emitterId || !file) {
        alert("Selecione o emissor e o arquivo primeiro");
        return;
      }

      setLoading(true);
      try {
        const response = await processarPGDAS(emitterId, file);

        // CORREÇÃO TELA BRANCA: O backend novo retorna { status: "ok", data: {...} }
        // Precisamos salvar o conteudo de 'data' no estado, não o objeto response inteiro.
        if (response.data) {
            setResultado(response.data);
        } else {
            // Fallback para caso o backend antigo ainda esteja respondendo
            setResultado(response);
        }

        const msg = response.msg || "PGDAS processado com sucesso!";
        // Use seu notificador ou alert padrão
        if (window.notify) window.notify(msg, "success");
        else alert(msg);

        // Recarrega a tabela
        const aliqs = await getAliquotasAtuais();
        setAliquotas(aliqs || []);

      } catch (err) {
        const msg = err?.response?.data?.detail || err?.message || "Erro ao processar.";
        if (window.notify) window.notify(msg, "error");
        else alert(msg);
      } finally {
        setLoading(false);
      }
  }

  function handleFileChange(e) {
    setFile(e.target.files[0] || null);
  }

  return (
    <div className="aliquota-container">
      <h1>Atualizar Alíquota (PGDAS)</h1>

      <div className="instructions">
        <p>
            Faça upload da declaração do PGDAS do mês mais recente.
            O sistema irá extrair automaticamente:
        </p>
        <ul>
            <li>Receita Bruta Acumulada (RBT12)</li>
            <li>Receita do mês (RPA)</li>
            <li>E recalcular a alíquota conforme o Simples Nacional.</li>
        </ul>
      </div>

      {/* --- FORMULÁRIO --- */}
      <div className="card">
        <form onSubmit={handleProcessar}>
          <div className="form-group">
            <label htmlFor="emitter-select">Selecione o Emissor:</label>
            <select
              id="emitter-select"
              className="filtro-input"
              value={emitterId}
              onChange={(e) => setEmitterId(e.target.value)}
            >
              <option value="">-- Selecione --</option>
              {emissores.map((e) => (
                <option key={e._id} value={e._id}>{e.razaoSocial}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>Upload do PGDAS (PDF):</label>
            <div className="file-upload-wrapper">
              <label htmlFor="file-upload" className="btn btn-secondary">
                Selecionar Arquivo
              </label>
              <input
                id="file-upload"
                type="file"
                accept="application/pdf"
                onChange={handleFileChange}
              />
              <span className="file-name">
                {file ? file.name : "Nenhum arquivo selecionado"}
              </span>
            </div>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn" disabled={loading}>
               {loading ? "Processando..." : "Processar PGDAS"}
            </button>
          </div>
        </form>
      </div>

      {/* --- CARD DE RESULTADO IMEDIATO --- */}
      {resultado && (
        <div className="card result-success">
          <h3>Resultado do Cálculo ({resultado.mes}/{resultado.ano})</h3>
          <div className="result-grid">
            <p><strong>RBT12:</strong> {formatMoney(resultado.rbt12)}</p>
            <p><strong>RPA Mês:</strong> {formatMoney(resultado.rpa_mes)}</p>
            <p><strong>Alíquota Efetiva:</strong> <span className="badge-aliquota">{formatPercent(resultado.aliquota)}</span></p>
          </div>
        </div>
      )}

      {/* --- ÁREA DE FILTROS --- */}
      <div className="card" style={{marginBottom: '10px', padding: '15px'}}>
          <h4 style={{marginBottom: '10px'}}>Filtros</h4>
          <div className="filtros-row" style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
            <div>
                <label style={{marginRight: '5px'}}>Mês:</label>
                <select value={filtroMes} onChange={e => setFiltroMes(e.target.value)} style={{padding: '5px'}}>
                    <option value="">Todos</option>
                    {mesesOpcoes.map(m => (
                        <option key={m} value={String(m)}>{String(m).padStart(2, '0')}</option>
                    ))}
                </select>
            </div>
            <div>
                <label style={{marginRight: '5px'}}>Ano:</label>
                <select value={filtroAno} onChange={e => setFiltroAno(e.target.value)} style={{padding: '5px'}}>
                    <option value="">Todos</option>
                    {anosOpcoes.map(a => (
                        <option key={a} value={String(a)}>{a}</option>
                    ))}
                </select>
            </div>
            <button
                className="btn btn-secondary"
                style={{padding: '5px 10px', fontSize: '0.8rem'}}
                onClick={() => { setFiltroMes(""); setFiltroAno(""); }}
            >
                Limpar
            </button>
          </div>
      </div>

      {/* --- TABELA DE HISTÓRICO --- */}
      {aliquotas.length > 0 ? (
        <div className="card">
          <h3>Histórico de Alíquotas</h3>
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="cell-left">Empresa</th>
                  <th className="cell-center">Mês/Ano</th>
                  <th className="cell-right">RBT12</th>
                  <th className="cell-right">RPA Mês</th>
                  <th className="cell-center">Alíquota</th>
                </tr>
              </thead>
              <tbody>
                {aliquotasFiltradas.map((a) => {
                  // CORREÇÃO IMPORTANTE: Busca pelo emitter_id, não pelo _id da alíquota
                  const emissor = emissores.find(e => e._id === a.emitter_id);

                  return (
                    <tr key={a._id}>
                      <td className="cell-left">
                          {emissor ? emissor.razaoSocial : "Empresa não encontrada"}
                      </td>
                      <td className="cell-center">
                        {String(a.mes).padStart(2, '0')}/{a.ano}
                      </td>
                      <td className="cell-right">{formatMoney(a.rbt12)}</td>
                      <td className="cell-right">{formatMoney(a.rpa_mes)}</td>
                      <td className="cell-center" style={{fontWeight: 'bold'}}>
                          {formatPercent(a.aliquota)}
                      </td>
                    </tr>
                  );
                })}

                {aliquotasFiltradas.length === 0 && (
                    <tr>
                        <td colSpan="5" style={{textAlign: 'center', padding: '20px'}}>
                            Nenhum resultado para os filtros selecionados.
                        </td>
                    </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="empty-state">Nenhum histórico encontrado.</p>
      )}
    </div>
  );
}