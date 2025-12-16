import { useState, useEffect, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import { Pencil, FilePlus2, Eraser } from 'lucide-react';
import "../styles/EmitirNota.css";
import CTNAutocomplete from "../components/CTNAutocomplete";
import {
  getEmitters,
  getClientsByEmitter,
  deleteDraft,
  listDrafts,
  getDraft,
  updateDraft,
  draftsImport,
  notasPreview,
  notasConfirmarFromDrafts,
  draftsReconcile,
  getAliquotaAtual
} from "../services/api";

// ------- helpers -------
const sanitizeDocument = (value) => (value ? String(value).replace(/\D/g, "") : "");
const formatCnpjCpf = (value) => {
  if (!value) return "";
  const sanitizedValue = sanitizeDocument(value);
  if (sanitizedValue.length === 11) return sanitizedValue.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  if (sanitizedValue.length === 14) return sanitizedValue.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
  return value;
};
const onlyDigits = (s = "") => String(s).replace(/\D/g, "");
const normalizeCTN = (v) => {
  if (!v && v !== 0) return "";
  let s = String(v).trim();
  const dash = s.indexOf(" - ");
  if (dash > -1) s = s.slice(0, dash).trim();
  const m = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{1,2})$/);
  if (m) {
    const a = m[1].padStart(2, "0"), b = m[2].padStart(2, "0"), c = m[3].padStart(2, "0");
    return `${a}.${b}.${c}`;
  }
  const digits = s.replace(/\D/g, "");
  if (digits.length === 6) return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4, 6)}`;
  if (digits.length === 5) {
    const norm = "0" + digits;
    return `${norm.slice(0, 2)}.${norm.slice(2, 4)}.${norm.slice(4, 6)}`;
  }
  return s;
};
const normalizeCTNOrNull = (v) => {
  const s = normalizeCTN(v);
  return s && s.trim() ? s : null;
};
const parseCompetencia = (value) => {
  const numericValue = (value || "").replace(/\D/g, "");
  if (numericValue.length < 6) return "";
  const month = numericValue.slice(0, 2);
  const year = numericValue.slice(2, 6);
  if (Number(month) < 1 || Number(month) > 12) return "";
  return `${year}-${month}`;
};
const formatCompetenciaInput = (value) => {
  if (!value) return "";
  const s = String(value).trim();
  if (value.includes("-") && value.length >= 7) {
    const [yyyy, mm] = value.split("-");
    const full = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (full) return `${full[3]}/${full[2]}/${full[1]}`;

  // "YYYY-MM" → MM/YYYY (fallback)
  const ym = s.match(/^(\d{4})-(\d{2})$/);
  if (ym) return `${ym[2]}/${ym[1]}`;

  return s;
};
  const numericValue = value.replace(/\D/g, "");
  if (numericValue.length <= 2) return numericValue;
  return `${numericValue.slice(0, 2)}/${numericValue.slice(2, 6)}`;
};
const formatAliquotaDisplay = (value) => {
  if (value == null || value === "") return "";
  const num = parseFloat(value);
  if (isNaN(num)) return "";
  // se já for decimal (0.1742), mostra 17.42%
  return (num < 1 ? num * 100 : num).toFixed(2) + "%";
};

const parseAliquotaInput = (value) => {
  if (!value) return "";
  const cleaned = String(value).replace("%", "").replace(",", ".").trim();
  const num = parseFloat(cleaned);
  if (isNaN(num)) return "";
  // se for digitado 17.42, salva como 0.1742
  return num > 1 ? num / 100 : num;
};


const CustomFileInput = ({ onChange, accept }) => {
  const [fileName, setFileName] = useState("Nenhum arquivo escolhido");
  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    setFileName(file ? file.name : "Nenhum arquivo escolhido");
    onChange?.(file || null);
  };
  return (
    <label className="custom-file-upload">
      <input type="file" accept={accept} onChange={handleFileChange} />
      <div className="upload-button">Escolher Arquivo</div>
      <div className="file-name">{fileName}</div>
    </label>
  );
};

export default function EmitirNota() {
  const [emissores, setEmissores] = useState([]);
  const [emissorAtivoId, setEmissorAtivoId] = useState(null);
  const [emissorAtivoObj, setEmissorAtivoObj] = useState(null);
  const [clientesVinculados, setClientesVinculados] = useState([]);
  const [busca, setBusca] = useState("");
  const [rowStatus, setRowStatus] = useState({});
  const [arquivoSelecionado, setArquivoSelecionado] = useState(null);
  const [pageSize, setPageSize] = useState(25);
  const [page, setPage] = useState(1);
  const [selectedByEmitter, setSelectedByEmitter] = useState({});
  const masterCheckboxRef = useRef(null);
  const [modalAberto, setModalAberto] = useState(false);
  const [modalCliente, setModalCliente] = useState(null);
  const [previewBatchId, setPreviewBatchId] = useState(null);
  const [modalForm, setModalForm] = useState({
    cpf_cnpj: "", valor: "", descricao: "", competencia: "", cod_servico: "",
    aliquota: "", municipio_ibge: "", pais_prestacao: "BRASIL", iss_retido: "N", data_emissao: "",
  });
  const [modalErrors, setModalErrors] = useState({});
  const [modalApiError, setModalApiError] = useState("");
  const [competenciaInput, setCompetenciaInput] = useState("");
  const [ctnOptions, setCtnOptions] = useState([]);
  const [sortConfig, setSortConfig] = useState({ key: 'nome', direction: 'ascending' });
  const [dupModalOpen, setDupModalOpen] = useState(false);
  const [dupGroups, setDupGroups] = useState([]);
  const [dupSelection, setDupSelection] = useState({});
  const [lastPreview, setLastPreview] = useState(null);
  const [addOutra, setAddOutra] = useState(false);
  const [modalBaseDraftId, setModalBaseDraftId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    fetch("/ctn_list.json")
      .then((r) => r.json())
      .then(setCtnOptions)
      .catch(() => setCtnOptions([]));
  }, []);

  const ctnMap = useMemo(() => {
    const m = new Map();
    for (const o of ctnOptions) m.set(o.code, o.label);
    return m;
  }, [ctnOptions]);

  useEffect(() => {
    const carregarDadosIniciais = async () => {
      setLoading(true);
      try {
        const data = await getEmitters();
        const emissoresArray = Array.isArray(data) ? data : [];
        setEmissores(emissoresArray);
      } catch (error) {
        console.error("Falha ao buscar emissores:", error);
        setEmissores([]);
      } finally {
        setLoading(false);
      }
    };
    carregarDadosIniciais();
  }, []);

  const hydrateFromDrafts = async (emitterId, { merge = true } = {}) => {
    try {
      const drafts = await listDrafts({ emitterId });
      const grouped = {};
      drafts.forEach((d) => {
        if (!d.client_id) return;
        const clienteId = d.client_id;
        const item = {
          index: d.origem?.preview_index || 0,
          emitterId: d.emitter_id,
          clienteId: d.client_id,
          cpf_cnpj: d.cpf_cnpj,
          cliente_nome: d.cliente_nome,
          valor: d.valor,
          descricao: d.descricao,
          competencia: d.competencia,
          cod_servico: normalizeCTNOrNull(d.cod_servico) ?? undefined,
          aliquota: d.aliquota,
          municipio_ibge: d.municipio_ibge,
          pais_prestacao: d.pais_prestacao,
          iss_retido: d.iss_retido,
          seq: d.seq || 1,
          duplicate_group_id: d.duplicate_group_id,
          erros: d.erros || [],
          ok: d.status ? d.status !== 'invalid' : true,
        };
        if (!grouped[clienteId]) grouped[clienteId] = [];
        grouped[clienteId].push({ draftId: d._id, item });
      });

      Object.keys(grouped).forEach((k) => {
        grouped[k].sort((a, b) => {
          const ca = a.item.competencia || "", cb = b.item.competencia || "";
          if (ca !== cb) return ca.localeCompare(cb);
          return (a.item.seq || 0) - (b.item.seq || 0);
        });
      });

      const next = {};
      Object.entries(grouped).forEach(([clienteId, draftsArr]) => {
        const firstDraftWithErrors = draftsArr.find(d => d.item && d.item.ok === false);
        next[clienteId] = {
          saved: true,
          ok: !firstDraftWithErrors,
          erros: firstDraftWithErrors ? (firstDraftWithErrors.item.erros || ['Erro']) : [],
          drafts: draftsArr
        };
      });

      if (merge) setRowStatus((prev) => ({ ...prev, ...next }));
      else setRowStatus(next);
    } catch (error) {
      console.error("Falha ao carregar rascunhos:", error);
    }
  };

    const handleEmissorClick = async (id, emissoresSource = emissores) => {
      const obj = (emissoresSource || []).find((e) => e._id === id) || null;
      setEmissorAtivoId(id);
      setEmissorAtivoObj(obj);
      setBusca("");
      setRowStatus({});
      setPage(1);
      setActionLoading(true);

      try {
        // 🔹 Buscar clientes
        const data = await getClientsByEmitter(id);
        const arr = (Array.isArray(data) ? data : []).filter(c => c.ativo !== false);
        arr.sort((a, b) => {
          const na = a.nao_identificado ? 1 : 0, nb = b.nao_identificado ? 1 : 0;
          if (na !== nb) return nb - na;
          return (a.nome || "").localeCompare(b.nome || "");
        });
        setClientesVinculados(arr);

        // 🔹 Buscar alíquota atual e aplicar no emissor ativo
        try {
          const aliq = await getAliquotaAtual(id);
          console.log("🔸 Alíquota recebida:", aliq);
          if (aliq && aliq.aliquota != null) {
            setEmissorAtivoObj((prev) => ({
              ...(prev || obj),
              aliquota_padrao: aliq.aliquota,
            }));
          }
        } catch (err) {
          console.warn("⚠️ Falha ao buscar alíquota:", err);
        }

        await hydrateFromDrafts(id, { merge: false });
      } catch (error) {
        console.error("Falha ao buscar clientes do emissor:", error);
        setClientesVinculados([]);
      } finally {
        setActionLoading(false);
      }
    };


  const requestSort = (key) => {
    let direction = 'ascending';
    if (sortConfig.key === key && sortConfig.direction === 'ascending') {
      direction = 'descending';
    }
    setSortConfig({ key, direction });
    setPage(1);
  };

const processedClientes = useMemo(() => {
    const q = (busca || "").toLowerCase().trim();
    const qSanitized = sanitizeDocument(q);

    let items = clientesVinculados.filter((c) => {
      if (!q) return true;
      const nome = (c.nome || "").toLowerCase();
      const docSanitized = sanitizeDocument(c.cnpj || c.cpf);
      return nome.includes(q) || (qSanitized.length > 0 && docSanitized.includes(qSanitized));
    });

    // Lógica de ordenação Aprimorada
    items.sort((a, b) => {
      const stA = rowStatus[a._id] || {};
      const stB = rowStatus[b._id] || {};

      // --- 1. Lógica primária: Clientes com dados vêm primeiro ---
      // (Verifica se existe algum rascunho salvo para o cliente)
      const aHasData = (stA.drafts?.length > 0 || stA.item);
      const bHasData = (stB.drafts?.length > 0 || stB.item);

      if (aHasData && !bHasData) return -1; // 'a' (com dados) vem antes
      if (!aHasData && bHasData) return 1;  // 'b' (com dados) vem antes

      const key = sortConfig.key || 'nome'; // Garante que sempre haja uma chave
      const direction = sortConfig.direction || 'ascending';

      let valA, valB;
      const getFromDrafts = (st, key) => {
        if (st?.drafts?.length) return st.drafts[0]?.item?.[key];
        if (st?.item) return st.item?.[key];
        return undefined;
      };

      if (['nome', 'cnpj', 'cpf'].includes(key)) {
        valA = a[key] || (a.cnpj || a.cpf);
        valB = b[key] || (b.cnpj || b.cpf);
      } else {
        valA = getFromDrafts(stA, key);
        valB = getFromDrafts(stB, key);
      }

      const valAExists = valA !== null && valA !== undefined && valA !== '';
      const valBExists = valB !== null && valB !== undefined && valB !== '';

      // Esta lógica empurra valores vazios *para a coluna específica* para baixo
      if (!valAExists && valBExists) return 1;
      if (valAExists && !valBExists) return -1;

      // Se ambos são vazios *naquela coluna*, ordena por nome como fallback
      if (!valAExists && !valBExists) {
        return (a.nome || "").localeCompare(b.nome || "");
      }

      const comparison = String(valA).localeCompare(String(valB), 'pt-BR', { numeric: true });
      return direction === 'ascending' ? comparison : -comparison;
    });

    return items;
  }, [clientesVinculados, busca, sortConfig, rowStatus]);

  const totalPages = Math.max(1, Math.ceil(processedClientes.length / pageSize));
  const pageSafe = Math.min(page, totalPages);
  const paginatedClientes = useMemo(() => {
    const start = (pageSafe - 1) * pageSize;
    return processedClientes.slice(start, start + pageSize);
  }, [processedClientes, pageSafe, pageSize]);

  const selectedMapForActive = selectedByEmitter[emissorAtivoId] || {};
  // --- 🔹 Controle de seleção de drafts ---
    const isSelected = (draftId) => !!selectedMapForActive[draftId];

    const selectedCountFiltered = useMemo(() => {
      let count = 0;
      for (const c of processedClientes) {
        const st = rowStatus[c._id] || {};
        const drafts = st.drafts || (st.item ? [{ draftId: st.draftId }] : []);
        for (const d of drafts) {
          if (d?.draftId && selectedMapForActive[d.draftId]) count++;
        }
      }
      return count;
    }, [processedClientes, rowStatus, selectedMapForActive]);

    const toggleOne = (draftId, checked) => {
      setSelectedByEmitter((prev) => {
        const current = { ...(prev[emissorAtivoId] || {}) };
        if (checked) current[draftId] = true;
        else delete current[draftId];
        return { ...prev, [emissorAtivoId]: current };
      });
    };

   const setAllFiltered = (checked) => {
      setSelectedByEmitter((prev) => {
        const current = { ...(prev[emissorAtivoId] || {}) };
        for (const c of processedClientes) {
          const st = rowStatus[c._id] || {};
          const drafts = st.drafts || (st.item ? [{ draftId: st.draftId }] : []);
          for (const d of drafts) {
            if (!d?.draftId) continue;
            if (checked) current[d.draftId] = true;
            else delete current[d.draftId];
          }
        }
        return { ...prev, [emissorAtivoId]: current };
      });

      // 🔹 força atualização visual imediata
      if (masterCheckboxRef.current) {
        masterCheckboxRef.current.indeterminate = false;
        masterCheckboxRef.current.checked = checked;
      }
    };

  useEffect(() => {
      if (!masterCheckboxRef.current) return;
      const total = processedClientes.reduce((acc, c) => {
        const st = rowStatus[c._id] || {};
        const drafts = st.drafts || (st.item ? [{ draftId: st.draftId }] : []);
        return acc + drafts.length;
      }, 0);

      masterCheckboxRef.current.indeterminate =
        selectedCountFiltered > 0 && selectedCountFiltered < total;
    }, [processedClientes, rowStatus, selectedCountFiltered]);


  const abrirModalCliente = async (c, targetDraftId = null) => {
    setAddOutra(false);
    setModalCliente({ ...c, __isAnon: !!c.nao_identificado });
    setModalErrors({});
    setModalApiError("");

    const st = rowStatus[c._id];
    let baseDraft = null;
      if (targetDraftId && st?.drafts?.length) {
        baseDraft = st.drafts.find(d => d.draftId === targetDraftId) || null;
      }
      if (!baseDraft && st?.drafts?.length) {
        baseDraft = st.drafts[st.drafts.length - 1];
    }
    setModalBaseDraftId(baseDraft?.draftId || st?.draftId || null);
   let form = {
      cpf_cnpj: c.cnpj || c.cpf || "",
      valor: "",
      descricao: "",
      competencia: "",
      cod_servico: "",
      aliquota: emissorAtivoObj?.aliquota_padrao ?? "",
      municipio_ibge: c.codigoIbge || "",
      pais_prestacao: "BRASIL",
      iss_retido: "N",
      data_emissao: ""
    };

    let compInput = "";
    try {
      if (baseDraft?.draftId) {
        const d = await getDraft(baseDraft.draftId);
        form = {
          cpf_cnpj: d.cpf_cnpj || c.cnpj || c.cpf || "", valor: d.valor ?? "", descricao: d.descricao || "",
          competencia: d.competencia || "", cod_servico: normalizeCTNOrNull(d.cod_servico) ?? "", aliquota: d.aliquota ?? "",
          municipio_ibge: d.municipio_ibge || c.codigoIbge || "", pais_prestacao: d.pais_prestacao || "BRASIL",
          iss_retido: d.iss_retido ? "S" : "N", data_emissao: d.dataEmissao ? d.dataEmissao.split("T")[0] : ""
        };
        compInput = d.competencia ? formatCompetenciaInput(d.competencia) : "";
      } else if (st?.item) {
        form = {
          cpf_cnpj: st.item.cpf_cnpj || c.cnpj || c.cpf || "", valor: st.item.valor ?? "", descricao: st.item.descricao || "",
          competencia: st.item.competencia || "", cod_servico: normalizeCTNOrNull(st.item.cod_servico) ?? "",
          aliquota: st.item.aliquota ?? "", municipio_ibge: st.item.municipio_ibge || c.codigoIbge || "",
          pais_prestacao: st.item.pais_prestacao || "BRASIL", iss_retido: st.item.iss_retido ? "S" : "N",
          data_emissao: d.dataEmissao ? d.dataEmissao.split("T")[0] : ""
        };
        compInput = st.item.competencia ? formatCompetenciaInput(st.item.competencia) : "";
      }
    } catch (err) {
      console.error("Falha ao carregar draft:", err);
    }
    setModalForm(form);
    setCompetenciaInput(compInput);
    setModalAberto(true);
    setTimeout(() => {
      const el = document.querySelector(".modal input[name='valor']");
      if (el) el.focus();
    }, 0);
  };

  const handleDuplicarDraft = async (draftId, cliente) => {
    if (!draftId) return;
    setActionLoading(true);
    try {
      const originalDraft = await getDraft(draftId);
      setModalBaseDraftId(null);
      setAddOutra(true);
      setModalCliente(cliente);
      const form = {
          cpf_cnpj: originalDraft.cpf_cnpj || cliente.cnpj || cliente.cpf || "",
          valor: originalDraft.valor ?? "",
          descricao: originalDraft.descricao || "",
          competencia: originalDraft.competencia || "",
          cod_servico: normalizeCTNOrNull(originalDraft.cod_servico) ?? "",
          aliquota: originalDraft.aliquota ?? "",
          municipio_ibge: originalDraft.municipio_ibge || cliente.codigoIbge || "",
          pais_prestacao: originalDraft.pais_prestacao || "BRASIL",
          iss_retido: originalDraft.iss_retido ? "S" : "N",
          data_emissao: originalDraft.dataEmissao
            ? originalDraft.dataEmissao.split("T")[0]
            : new Date().toISOString().split("T")[0],
      };

      const compInput = originalDraft.competencia ? formatCompetenciaInput(originalDraft.competencia) : "";
      setModalForm(form);
      setCompetenciaInput(compInput);
      setModalErrors({});
      setModalApiError("");
      setModalAberto(true);
    } catch (err) {
      console.error("Falha ao duplicar Nota:", err);
      window.notify("Não foi possível carregar os dados para duplicação.");
    } finally {
      setActionLoading(false);
    }
  };

  const fecharModal = () => {
    setModalAberto(false);
    setModalCliente(null);
    setModalBaseDraftId(null);
    setAddOutra(false);
    setModalErrors({});
    setModalApiError("");
  };

 const salvarModal = async () => {
  setModalErrors({});
  setModalApiError("");

  if (!emissorAtivoId) {
    setModalApiError("Selecione um emissor.");
    return;
  }
  const f = modalForm;

  // --- NOVO: Bloco de Validação ---
  const errors = {};
  if (!f.valor) {
    errors.valor = "O campo Valor é obrigatório.";
  }
  if (!f.descricao) {
    errors.descricao = "O campo Descrição é obrigatório.";
  }
  if (!f.cpf_cnpj && !modalCliente?.__isAnon) {
    errors.cpf_cnpj = "O campo CPF/CNPJ é obrigatório.";
  }

  if (Object.keys(errors).length > 0) {
    setModalErrors(errors);
    return;
  }
  // --- Fim do Bloco de Validação ---

  const dataEmissaoISO = modalForm.data_emissao
  ? new Date(modalForm.data_emissao).toISOString()
  : new Date().toISOString();

  const fileContent = {
    cpf_cnpj: f.cpf_cnpj,
    valor: String(f.valor).replace(",", "."),
    descricao: f.descricao,
    competencia: f.competencia || "",
    cod_servico: normalizeCTNOrNull(f.cod_servico) || "",
    aliquota: emissorAtivoObj?.aliquota_padrao || "",
    municipio_ibge: f.municipio_ibge || "",
    pais_prestacao: f.pais_prestacao || "",
    iss_retido: (f.iss_retido || "").toUpperCase(),
    dataEmissao: dataEmissaoISO,
  };

  const file = new Blob([JSON.stringify(fileContent)], { type: "application/json" });

  setActionLoading(true);
  try {
    const data = await notasPreview({
      emitterId: emissorAtivoId,
      file: new File([file], "manual.json"),
      persistManual: !addOutra,
    });

    const linhaPreview = (data?.linhas || [])[0];
    if (!linhaPreview.clienteId && modalCliente?._id) {
      linhaPreview.clienteId = modalCliente._id;
    }

    linhaPreview.cod_servico = normalizeCTNOrNull(linhaPreview.cod_servico) ?? null;

    let cliente = (linhaPreview?.clienteId &&
      clientesVinculados.find((c) => c._id === linhaPreview.clienteId)) || null;
    if (!cliente) {
      const d = onlyDigits(f.cpf_cnpj);
      if (d)
        cliente =
          clientesVinculados.find(
            (c) => onlyDigits(c.cnpj || c.cpf || "") === d
          ) || null;
    }
    if (!cliente && modalCliente?.__isAnon) cliente = modalCliente;

    if (cliente) {
      setRowStatus((prev) => ({
        ...prev,
        [cliente._id]: {
          ...(prev[cliente._id] || {}),
          saved: true,
          ok: !!linhaPreview.ok,
          erros: linhaPreview.ok ? [] : (linhaPreview.erros || []),
          item: linhaPreview,
        },
      }));
    }

    if (linhaPreview?.ok) {
      const clienteIdKey = cliente?._id || linhaPreview?.clienteId || null;
      const existingDraftId = clienteIdKey ? modalBaseDraftId : null;
      const payloadDraft = {
        valor: Number(linhaPreview.valor),
        descricao: linhaPreview.descricao,
        competencia: linhaPreview.competencia,
        aliquota: Number(linhaPreview.aliquota),
        municipio_ibge: linhaPreview.municipio_ibge || null,
        pais_prestacao: linhaPreview.pais_prestacao || "BRASIL",
        iss_retido: !!linhaPreview.iss_retido,
        cod_servico: normalizeCTNOrNull(linhaPreview.cod_servico) ?? null,
        dataEmissao: dataEmissaoISO,
      };

      if (addOutra) {
        const safeClienteId = (cliente && cliente._id) || linhaPreview.clienteId;
        await draftsImport(emissorAtivoId, [
          {
              emitterId: emissorAtivoId,
              cpf_cnpj: linhaPreview.cpf_cnpj || f.cpf_cnpj,
              clienteId: safeClienteId,
              descricao: linhaPreview.descricao,
              valor: Number(linhaPreview.valor),
              competencia: linhaPreview.competencia,
              aliquota: Number(linhaPreview.aliquota || 0),
              municipio_ibge: linhaPreview.municipio_ibge || null,
              pais_prestacao: linhaPreview.pais_prestacao || "BRASIL",
              iss_retido: !!linhaPreview.iss_retido,
              cod_servico: normalizeCTNOrNull(linhaPreview.cod_servico),
              dataEmissao: dataEmissaoISO,
              force_new: true,
              duplicate_confirmed: true,
              ok: true
          },
        ]);
      } else {
        if (existingDraftId) {
          await updateDraft(existingDraftId, payloadDraft);
        } else {
          await draftsImport(emissorAtivoId, [
            {
              emitterId: emissorAtivoId,
              cpf_cnpj: linhaPreview.cpf_cnpj || f.cpf_cnpj,
              clienteId: linhaPreview.clienteId,
              descricao: linhaPreview.descricao,
              valor: Number(linhaPreview.valor),
              competencia: linhaPreview.competencia,
              aliquota: Number(linhaPreview.aliquota),
              municipio_ibge: linhaPreview.municipio_ibge || null,
              pais_prestacao: linhaPreview.pais_prestacao || "BRASIL",
              iss_retido: !!linhaPreview.iss_retido,
              cod_servico: normalizeCTNOrNull(linhaPreview.cod_servico),
              dataEmissao: dataEmissaoISO,
            },
          ]);
        }
      }

      await hydrateFromDrafts(emissorAtivoId, { merge: false });
    } else {
      setModalApiError((linhaPreview.erros || ["Erro ao validar prévia."]).join("; "));
      setActionLoading(false);
      return;
    }

    fecharModal();
  } catch (e) {
    console.error(e);
    setModalApiError(e.message || "Falha ao validar/salvar a nota.");
  } finally {
    setActionLoading(false);
  }
};


  const onUpload = async (file) => {
    if (!emissorAtivoId || !file) return;
    setActionLoading(true);
    try {
      const data = await notasPreview({ emitterId: emissorAtivoId, file });
      setLastPreview(data);
      setPreviewBatchId(data.preview_batch_id || null);

      const byKey = new Map();
      const toMonth = (comp) => String(comp || "").slice(0, 7);
      for (const l of (data.linhas || [])) {
        const cpf = (String(l.cpf_cnpj || "").match(/\d+/g) || []).join("");
        const cid = l.clienteId || cpf || "ANON";
        const key = `${cid}|${toMonth(l.competencia)}|${emissorAtivoId}`;
        if (!byKey.has(key)) byKey.set(key, []);
        byKey.get(key).push(l);
      }
      const dups = [...byKey.entries()]
        .filter(([, arr]) => arr.length > 1)
        .map(([chave, linhas]) => ({ chave, linhas }));


      const byId = {};

      for (const l of (data.linhas || [])) {
        const ctn = normalizeCTNOrNull(l.cod_servico);
        if (ctn) l.cod_servico = ctn; else delete l.cod_servico;

        let cliente =
          (l.clienteId && clientesVinculados.find(c => c._id === l.clienteId)) || null;

        if (!cliente) {
          const d = onlyDigits(l.cpf_cnpj || "");
          if (d)
            cliente = clientesVinculados.find(c => onlyDigits(c.cnpj || c.cpf || "") === d) || null;
        }

        if (!cliente) {
          window.notify("Verifique o emissor. A planilha contém clientes não vinculados.", "error");
          setActionLoading(false);
          return;
        }

        if (!byId[cliente._id]) {
          byId[cliente._id] = {
            saved: false,
            ok: true,
            erros: [],
            drafts: []
          };
        }
        byId[cliente._id].drafts.push({
          draftId: l.draftId || null,
          item: l
        });

        if (l.ok === false) {
          byId[cliente._id].ok = false;
          byId[cliente._id].erros = [...byId[cliente._id].erros, ...(l.erros || ["Erro na validação"])];
        }
      }

      setRowStatus(prev => ({ ...prev, ...byId }));

      if (dups.length > 0) {
        const defaultSel = {};
        dups.forEach((g) => {
          const sel = {};
          (g.linhas || []).forEach((ln) => { sel[ln.index] = true; });
          defaultSel[g.chave] = sel;
        });
        setDupSelection(defaultSel);
        setDupGroups(dups);
        setDupModalOpen(true);
        return;
      }

      await hydrateFromDrafts(emissorAtivoId, { merge: true });
    } catch (e) {
      console.error(e);
      window.notify(e.message || "Falha ao pré-visualizar a planilha.");
    } finally {
      setActionLoading(false);
    }
  };

  const enviarArquivo = async () => {
    if (!arquivoSelecionado) return;
    await onUpload(arquivoSelecionado);
    setArquivoSelecionado(null);
  };

  const gerarTasks = async () => {
    if (!emissorAtivoId) return window.notify("Selecione um emissor.");
    const draftIds = Object.keys(selectedByEmitter[emissorAtivoId] || {});
    if (draftIds.length === 0) return window.notify("Selecione pelo menos uma prévia para gerar o XML.");


    setActionLoading(true);
    try {
      const data = await notasConfirmarFromDrafts({ emitterId: emissorAtivoId, draftIds });
      if (Array.isArray(data.erros) && data.erros.length) {
        window.notify(`${data.msg}\n${data.erros.length} notas falharam.`);
      } else {
        window.notify(data.msg);
      }
      await hydrateFromDrafts(emissorAtivoId, { merge: false });
    } catch (e) {
      console.error(e);
        window.notify(e.message || "Falha ao gerar XMLs.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCompetenciaChange = (e) => {
    const rawInput = e.target.value;
    const formattedInput = formatCompetenciaInput(rawInput);
    setCompetenciaInput(formattedInput);
    const apiValue = parseCompetencia(formattedInput);
    setModalForm({ ...modalForm, competencia: apiValue });
  };
    const handleLimparDraft = async (draftId, cliente) => {
      if (!draftId) return;

      const confirmar = await window.confirmDialog(`Deseja realmente limpar os campos da nota de "${cliente.nome}"?`);
      if (!confirmar) return;


      setActionLoading(true);
      try {
        await deleteDraft(draftId);
        await hydrateFromDrafts(emissorAtivoId, { merge: false });
        window.notify("Rascunho limpo com sucesso!");
      } catch (err) {
        console.error(err);
        window.notify(err.message || "Erro ao limpar rascunho.");
      } finally {
        setActionLoading(false);
      }
    };


  const totalValidas = Object.values(rowStatus).filter((s) => s.saved && s.ok).length;
  const totalInvalidas = Object.values(rowStatus).filter((s) => s.saved && !s.ok).length;

  const totalDraftsFiltered = processedClientes.reduce((acc, c) => {
      const st = rowStatus[c._id] || {};
      const drafts = st.drafts || (st.item ? [{ draftId: st.draftId }] : []);
      return acc + drafts.length;
  }, 0);

  const allFilteredSelected = totalDraftsFiltered > 0 && selectedCountFiltered === totalDraftsFiltered;


  const closeDupModal = () => {
    setDupModalOpen(false);
    setDupGroups([]);
  };

const confirmDupModal = async () => {
  const keep = [];
  const pool = [];
  (dupGroups || []).forEach(g => {
    const sel = dupSelection?.[g.chave] || {};
    (g.linhas || []).forEach(ln => {
      pool.push(ln.index);
      if (sel[ln.index]) keep.push(ln.index);
    });
  });

  setActionLoading(true);
  try {
    await draftsReconcile({
      emitterId: emissorAtivoId,
      preview_batch_id: previewBatchId,
      keep_indices: keep,
      group_indices: pool
    });
    await hydrateFromDrafts(emissorAtivoId, { merge: true });
  } catch (e) {
    console.error(e);
    window.notify(e.message || "Falha ao salvar duplicadas.");
  } finally {
    setActionLoading(false);
    closeDupModal();
  }
};



  if (loading) {
    return (
      <div className="container">
        <h1>Emitir Notas</h1>
        <p style={{ textAlign: "center", marginTop: "40px" }}>Carregando dados...</p>
      </div>
    );
  }

  if (!emissores || emissores.length === 0) {
    return (
      <div className="container">
        <h1>Emitir Notas</h1>
        <div className="empty-state-card">
          <h2>Nenhum emissor encontrado</h2>
          <p>Para começar a emitir notas, você precisa primeiro cadastrar um emissor.</p>
          <Link to="/emissores" className="btn">Cadastrar Emissor</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      <h1>Emitir Notas</h1>
      <div className="tab-container">
        {emissores.map((e) => (
          <button
            key={e._id}
            className={`tab-button ${e._id === emissorAtivoId ? "active" : ""}`}
            onClick={() => handleEmissorClick(e._id)}
          >
            <div className="tab-empresa">{e.razaoSocial}</div>
            <div className="tab-cnpj">{e.cnpj}</div>
          </button>
        ))}
      </div>
      {!emissorAtivoId ? (
          <div className="empty-state-card" style={{ marginTop: 40 }}>
            <p>Escolha um emissor acima para começar.</p>
          </div>
        ) : (
          <>
        <div className="emissor-selecionado-info">
            <strong style={{ marginRight: 5 }}>Emissor selecionado:</strong>
            <span className="emissor-selecionado-detalhe">
              {emissorAtivoObj ? `${emissorAtivoObj.razaoSocial} — ${emissorAtivoObj.cnpj}` : "—"}
            </span>
          </div>
        <div className="emitir-filtros-container">
            <input
              type="text"
              className="search-input"
              placeholder="Buscar cliente (nome, documento)"
              value={busca}
              onChange={(e) => { setBusca(e.target.value); setPage(1); }}
              style={{ maxWidth: "none", flex: 1 }}
            />
            <CustomFileInput accept=".xlsx,.csv" onChange={setArquivoSelecionado} />
            <button
              className="btn-enviar"
              disabled={!arquivoSelecionado || actionLoading}
              onClick={enviarArquivo}
            >
              {actionLoading ? "Enviando..." : "Enviar"}
            </button>
          </div>
          <table className="data-table emitir-nota-table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th className="col-check">
                    <input
                      ref={masterCheckboxRef}
                      type="checkbox"
                      checked={allFilteredSelected}
                      onChange={() => setAllFiltered(!allFilteredSelected)}
                      title="Selecionar/Desmarcar todos os clientes do filtro atual (todas as páginas)"
                    />
                </th>
                <th className="col-cliente sortable-header" onClick={() => requestSort("nome")}>Cliente {sortConfig.key === "nome" && (sortConfig.direction === "ascending" ? "▲" : "▼")}</th>
                <th className="col-documento sortable-header" onClick={() => requestSort("cnpj")}>CPF/CNPJ {sortConfig.key === "cnpj" && (sortConfig.direction === "ascending" ? "▲" : "▼")}</th>
                <th className="col-descricao sortable-header" onClick={() => requestSort("descricao")}>Descrição {sortConfig.key === "descricao" && (sortConfig.direction === "ascending" ? "▲" : "▼")}</th>
                <th className="col-valor sortable-header" onClick={() => requestSort("valor")}>Valor (R$) {sortConfig.key === "valor" && (sortConfig.direction === "ascending" ? "▲" : "▼")}</th>
                <th className="col-small">Aliq.</th>
                <th className="col-small">CTN</th>
                <th className="col-medium">Município</th>
                <th className="col-medium sortable-header" onClick={() => requestSort("competencia")}>Competência {sortConfig.key === "competencia" && (sortConfig.direction === "ascending" ? "▲" : "▼")}</th>
                <th className="col-status">Status</th>
                <th className="col-actions">Ações</th>
              </tr>
            </thead>
            <tbody>
              {paginatedClientes.length === 0 ? (
                <tr><td colSpan={11} style={{ textAlign: "center" }}>Nenhum cliente encontrado.</td></tr>
              ) : (paginatedClientes.map((c) => {
                const st = rowStatus[c._id] || {};
                const draftsArr = st.drafts || (st.item ? [{ draftId: st.draftId, item: st.item }] : []);
                if (draftsArr.length === 0) {
                  const checked = isSelected(c._id);
                  return (
                    <tr key={`${c._id}-empty`} onClick={() => abrirModalCliente(c)} style={{ cursor: "pointer" }}>
                      <td className="col-check" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={checked} disabled title="Selecionar cliente" /></td>
                      <td className="col-cliente" data-full={c.nome}>
                        <div className="truncate-wrapper">{c.nome}</div>
                      </td>
                      <td className="col-documento">{formatCnpjCpf(c.cnpj || c.cpf) || "—"}</td>
                      <td className="col-descricao">—</td>
                      <td className="col-valor">—</td>
                      <td className="col-small">
                         {formatAliquotaDisplay(emissorAtivoObj?.aliquota_padrao) || "—"}
                      </td>
                      <td className="col-small">—</td>
                      <td className="col-medium">{c.codigoIbge || "—"}</td>
                      <td className="col-medium">—</td>
                      <td className="col-status">—</td>
                      <td className="col-actions"><button className="action-button" onClick={(e) => { e.stopPropagation(); abrirModalCliente(c); }} title="Adicionar Nota"><Pencil size={16} /></button></td>
                    </tr>
                  );
                }
                return draftsArr.map((d, idx) => {
                  const it = d.item || {};
                  const ctnNorm = normalizeCTNOrNull(it.cod_servico);
                  const ctnDesc = ctnNorm ? ctnMap.get(ctnNorm) || "" : "";
                  const trKey = `${c._id}-${d.draftId || "tmp"}-${idx}`;
                  const checked = isSelected(d.draftId);
                  return (
                    <tr key={trKey} onClick={() => abrirModalCliente(c, d.draftId)} style={{ cursor: "pointer" }}>
                      <td className="col-check" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={checked} onChange={(e) => toggleOne(d.draftId, e.target.checked)} title="Selecionar prévia" /></td>
                      <td className="col-cliente" data-full={c.nome}>
                        <div className="truncate-wrapper">{c.nome}</div>
                      </td>
                      <td className="col-documento">{formatCnpjCpf(c.cnpj || c.cpf) || "-"}</td>
                      <td className="col-descricao" data-full={it.descricao || "—"}>
                          <div className="truncate-wrapper">
                            {it.descricao || "—"}
                          </div>
                      </td>
                      <td className="col-valor">{it.valor != null ? Number(it.valor).toFixed(2) : "—"}</td>
                      <td className="col-small">
                          {formatAliquotaDisplay(
                            it.aliquota != null && it.aliquota !== ""
                              ? it.aliquota
                              : emissorAtivoObj?.aliquota_padrao
                          ) || "—"}
                      </td>
                      <td className="col-medium" title={ctnDesc}>{ctnNorm || "—"}</td>
                      <td className="col-medium">{it.municipio_ibge || c.codigoIbge || "—"}</td>
                      <td className="col-medium">{it.competencia ? formatCompetenciaInput(it.competencia) : "—"}</td>
                      <td className="col-status">
                          {d.item.ok !== false ? (
                            <span className="status-badge status-badge-ok">OK</span>
                          ) : (
                            <span
                              className="status-badge status-badge-erro"
                              title={(d.item.erros || []).join("; ")}
                            >ERRO
                            </span>
                          )}
                      </td>
                      <td className="col-actions">
                         <button className="action-button" onClick={(e) => { e.stopPropagation(); abrirModalCliente(c, d.draftId); }} title="Editar"><Pencil size={16} /></button>
                        <button className="action-button" onClick={(e) => { e.stopPropagation(); handleDuplicarDraft(d.draftId, c); }} title="Duplicar"><FilePlus2 size={16} color="#4CAF50" /></button>
                        <button className="action-button" onClick={(e) => { e.stopPropagation(); handleLimparDraft(d.draftId, c); }} title="Limpar campos da nota"><Eraser size={16} color="#ba1b13" /></button>
                      </td>
                    </tr>
                  );
                });
              }))}
            </tbody>
          </table>
          <div className="actions-container">
    <button className="btn" disabled={actionLoading} onClick={gerarTasks}>{actionLoading ? "Emitindo..." : "Emitir Nota"}</button>
    {processedClientes.length > 0 && (
        <button
            className="btn btn-secondary"
            onClick={() => {
                setAllFiltered(false);
                setBusca("");
                setPage(1);
            }}
            disabled={selectedCountFiltered === 0 && !busca}
            title="Limpar seleção e filtros"
        >
            Limpar seleção e filtros
        </button>
    )}
</div>

{processedClientes.length > 0 && (
    <div className="pagination-controls">
        <div>
            <label htmlFor="pageSize">Itens por página: </label>
            <select
                id="pageSize"
                value={pageSize}
                onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            >
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
            </select>
        </div>
        <span>
            Página {page} de {totalPages || 1} ({processedClientes.length} clientes)
        </span>
        <div>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>Anterior</button>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages || totalPages === 0}>Próximo</button>
        </div>
    </div>
)}

          {modalAberto && (
            <div className="modal-overlay">
              <div className="modal modal--wide">
                <button className="modal-close" onClick={fecharModal}>&times;</button>
                <h3 style={{ marginTop: 0 }}>{addOutra ? "Nova Nota (Cópia)" : (modalBaseDraftId ? "Editar Nota" : "Nova Nota")} — {modalCliente?.nome || ""}</h3>

                {modalApiError && (
                  <div className="modal-error-message">
                    {modalApiError}
                  </div>
                )}

                <div className="form-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                  <div>
                    <label>CPF/CNPJ</label>
                    <input
                      value={modalForm.cpf_cnpj}
                      onChange={(e) => setModalForm({ ...modalForm, cpf_cnpj: e.target.value })}
                      disabled={modalCliente?.__isAnon}
                      className={modalErrors.cpf_cnpj ? 'input-error' : ''}
                    />
                    {modalErrors.cpf_cnpj && <div className="field-error">{modalErrors.cpf_cnpj}</div>} {/* --- NOVO --- */}
                    {modalCliente?.__isAnon && (<div className="field-hint">CPF/CNPJ <strong>opcional</strong> — este emissor permite emissão sem tomador identificado.</div>)}
                  </div>
                  <div>
                    <label>Valor (R$)</label>
                    <input
                      name="valor"
                      value={modalForm.valor}
                      onChange={(e) => setModalForm({ ...modalForm, valor: e.target.value })}
                      className={modalErrors.valor ? 'input-error' : ''}
                    />
                    {modalErrors.valor && <div className="field-error">{modalErrors.valor}</div>} {/* --- NOVO --- */}
                  </div>
                  <div>
                      <label>Data de Emissão</label>
                      <input type="date" value={modalForm.data_emissao || ""} onChange={(e) => setModalForm({ ...modalForm, data_emissao: e.target.value })}/>
                  </div>
                  <div style={{ gridColumn: "1 / span 3" }}>
                    <label>Descrição</label>
                    <textarea
                      value={modalForm.descricao}
                      onChange={(e) => setModalForm({ ...modalForm, descricao: e.target.value })}
                      rows={3}
                      className={`description-modal-input ${modalErrors.descricao ? 'input-error' : ''}`}
                    />
                    {modalErrors.descricao && <div className="field-error">{modalErrors.descricao}</div>} {/* --- NOVO --- */}
                  </div>
                  <div className="field-ctn">
                    <label>Código de Serviço (CTN)</label>
                    <CTNAutocomplete options={ctnOptions} value={normalizeCTNOrNull(modalForm.cod_servico) || ""} onChange={(code) => setModalForm({ ...modalForm, cod_servico: code })} />
                  </div>
                  <div>
                    <label>Município IBGE</label>
                    <input value={modalForm.municipio_ibge} onChange={(e) => setModalForm({ ...modalForm, municipio_ibge: e.target.value })} />
                  </div>
                  <div>
                    <label>País da prestação</label>
                    <input value={modalForm.pais_prestacao} onChange={(e) => setModalForm({ ...modalForm, pais_prestacao: e.target.value })} />
                  </div>
                  <div>
                    <label>ISS retido?</label>
                    <select value={modalForm.iss_retido} onChange={(e) => setModalForm({ ...modalForm, iss_retido: e.target.value })}>
                      <option value="N">Não</option>
                      <option value="S">Sim</option>
                    </select>
                  </div>
                </div>
                <div className="modal-actions">
                  <button className="btn btn-secondary" onClick={fecharModal}>Cancelar</button>
                  <button className="btn" disabled={actionLoading} onClick={salvarModal}>{actionLoading ? "Validando..." : addOutra ? "Adicionar outra" : "Adicionar/Atualizar prévia"}</button>
                </div>
              </div>
            </div>
          )}

          {dupModalOpen && (
            <div className="modal-overlay">
              <div className="modal modal--wide">
                <button className="modal-close" onClick={closeDupModal}>&times;</button>
                <h3 style={{ marginTop: 0 }}>Resolver duplicidades</h3>
                <p>Selecione quais linhas deseja manter por grupo. Se mantiver mais de uma no mesmo período, criaremos rascunhos adicionais.</p>
                <div style={{ maxHeight: 380, overflow: "auto", marginTop: 8 }}>
                  {(dupGroups || []).map((g) => (
                    <div key={g.chave} style={{ border: "1px solid var(--border-color)", borderRadius: 8, padding: 12, marginBottom: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 8 }}>Chave: {g.chave} • {g.linhas?.length || 0} linhas</div>
                      {(g.linhas || []).map((ln) => {
                        const checked = !!dupSelection[g.chave]?.[ln.index];
                        return (
                          <label key={ln.index} style={{ display: "grid", gridTemplateColumns: "24px 1fr", gap: 8, alignItems: "start", padding: "6px 0" }}>
                            <input type="checkbox" checked={checked} onChange={(e) => {
                              setDupSelection((prev) => {
                                const next = { ...(prev || {}) };
                                const inner = { ...(next[g.chave] || {}) };
                                inner[ln.index] = e.target.checked;
                                next[g.chave] = inner;
                                return next;
                              });
                            }} />
                            <div>
                              <div><strong>Linha {ln.index}</strong> — {ln.descricao} • R$ {Number(ln.valor).toFixed(2)}</div>
                              <div style={{ fontSize: 12, color: "var(--text-light-color)" }}>Competência: {ln.competencia} • CTN: {normalizeCTNOrNull(ln.cod_servico) || "—"} • Município: {ln.municipio_ibge || "—"}</div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  ))}
                </div>
                <div className="modal-actions">
                  <button className="btn btn-secondary" onClick={closeDupModal}>Cancelar</button>
                  <button className="btn" disabled={actionLoading} onClick={confirmDupModal}>{actionLoading ? "Salvando..." : "Confirmar e Salvar"}</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}