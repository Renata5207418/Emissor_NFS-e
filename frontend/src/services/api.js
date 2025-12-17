import axios from 'axios';

// Usa a variável de ambiente do Vite, com um fallback para desenvolvimento local
const API_URL = import.meta.env.VITE_API_URL || "http://10.0.0.172:6600";

// Cria uma instância do axios com configurações base
const apiClient = axios.create({
  baseURL: API_URL,
});

// Interceptor de Requisição: adiciona o token de autenticação em cada chamada
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('accessToken');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Interceptor de Resposta: trata 401 globalmente
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('accessToken');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// --- helper p/ extrair nome do arquivo do Content-Disposition ---
function pickFileName(contentDisposition, fallback) {
  if (!contentDisposition) return fallback;
  // filename*=UTF-8''nome.pdf
  const star = /filename\*\=UTF-8''([^;]+)/i.exec(contentDisposition);
  if (star) return decodeURIComponent(star[1]);
  // filename="nome.pdf" ou filename=nome.pdf
  const plain = /filename="?([^"]+)"?/i.exec(contentDisposition);
  return plain ? plain[1] : fallback;
}

/* =======================
 * AUTENTICAÇÃO
 * ======================= */
export async function login(email, password) {
  const formData = new FormData();
  formData.append('username', email);
  formData.append('password', password);
  const response = await apiClient.post('/auth/token', formData);
  if (response.data.access_token) {
    localStorage.setItem('accessToken', response.data.access_token);
    await getMe();
  }
  return response.data;
}

export async function register(name, email, password) {
  const response = await apiClient.post('/auth/register', { name, email, password });
  return response.data;
}
export async function forgotPassword(email) {
  // O backend espera um JSON { "email": "..." }
  const response = await apiClient.post('/auth/forgot-password', { email });
  return response.data;
}

export async function resetPassword(token, new_password) {
  // O backend espera { "token": "...", "new_password": "..." }
  const response = await apiClient.post('/auth/reset-password', { token, new_password });
  return response.data;
}
export function logout() {
  localStorage.removeItem('accessToken');
  localStorage.removeItem('user');
  window.location.href = '/login';
}

/* =======================
 * EMITTERS
 * ======================= */
export async function getEmitters() {
  const response = await apiClient.get('/emitters');
  return response.data;
}

export async function createEmitter(formData) {
  // usa axios ?puro? com header Authorization manual (mantido)
  const token = localStorage.getItem('accessToken');
  const response = await axios.post(`${API_URL}/emitters`, formData, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  return response.data;
}

export async function updateEmitter(id, emitterPartialJson) {
  const response = await apiClient.put(`/emitters/${id}`, emitterPartialJson);
  return response.data;
}

export async function deleteEmitter(id) {
  const response = await apiClient.delete(`/emitters/${id}`);
  return response.data;
}

export async function uploadEmitterCertificate(emitterId, file, senha) {
  // usa axios ?puro? com header Authorization manual (mantido)
  const token = localStorage.getItem('accessToken');
  const fd = new FormData();
  fd.append("file", file);
  fd.append("senha", senha);

  const response = await axios.post(`${API_URL}/emitters/${emitterId}/certificate`, fd, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  return response.data;
}

export async function getClientsByEmitter(emitterId) {
  const response = await apiClient.get(`/emitters/${emitterId}/clients`);
  return response.data;
}

export async function attachClientToEmitter(emitterId, clientId) {
  const response = await apiClient.post(`/emitters/${emitterId}/clients/${clientId}`);
  return response.data;
}

export async function detachClientFromEmitter(emitterId, clientId) {
  const response = await apiClient.delete(`/emitters/${emitterId}/clients/${clientId}`);
  return response.data;
}

/* =======================
 * CLIENTS
 * ======================= */
export async function getClients({ incluirInativos = false } = {}) {
  const response = await apiClient.get('/clients', { params: { incluir_inativos: incluirInativos } });
  return response.data;
}

export async function reativarClient(id) {
  const response = await apiClient.put(`/clients/${id}/reativar`);
  return response.data;
}

export async function createClient(clientJson) {
  const response = await apiClient.post('/clients', clientJson);
  return response.data;
}

export async function updateClient(id, clientPartialJson) {
  const response = await apiClient.put(`/clients/${id}`, clientPartialJson);
  return response.data;
}

export async function deleteClient(id) {
  const response = await apiClient.delete(`/clients/${id}`);
  return response.data;
}

export async function importClients(file) {
  const fd = new FormData();
  fd.append("file", file);
  const response = await apiClient.post('/clients/import', fd);
  return response.data;
}

export async function getClientStats() {
  const response = await apiClient.get("/clients/stats");
  return response.data;
}

export async function getClientsUpdatedRecently() {
  const response = await apiClient.get("/clients/recent-updates");
  return response.data;
}

export async function clearRecentClientUpdates() {
  const response = await apiClient.post("/clients/clear-recent-updates");
  return response.data;
}

/* =======================
 * NOTAS (preview/confirm)
 * ======================= */
export async function notasPreview({ emitterId, file, competenciaDefault, persistManual = true }) {
  const fd = new FormData();
  fd.append("emitterId", emitterId);
  if (competenciaDefault) fd.append("competenciaDefault", competenciaDefault);
  if (!persistManual) fd.append("persist", "0");
  fd.append("file", file);
  const response = await apiClient.post('/notas/preview', fd);
  return response.data;
}

export async function notasConfirmar({ emitterId, items }) {
  const response = await apiClient.post('/notas/confirmar', { emitterId, items });
  return response.data;
}

export async function notasConfirmarFromDrafts({ emitterId, draftIds }) {
  const response = await apiClient.post('/notas/confirmar-from-drafts', { emitterId, draftIds });
  return response.data;
}

/* =======================
 * DRAFTS (rascunhos persistentes)
 * ======================= */
export async function draftsImport(emitterId, items) {
  const response = await apiClient.post('/notas/drafts/import', {
    emitterId,
    items: items.map(i => ({ ...i }))
  });
  return response.data;
}

export async function listDrafts({ emitterId, status = 'active', clientId } = {}) {
  if (!emitterId) return [];
  const params = { emitterId, status };
  if (clientId) params.clientId = clientId;
  const response = await apiClient.get('/notas/drafts', { params });
  return response.data;
}

export async function getDraft(draftId) {
  const response = await apiClient.get(`/notas/drafts/${draftId}`);
  return response.data;
}

export async function updateDraft(draftId, partial) {
  const response = await apiClient.put(`/notas/drafts/${draftId}`, partial);
  return response.data;
}

export async function deleteDraft(draftId) {
  const response = await apiClient.delete(`/notas/drafts/${draftId}`);
  return response.data;
}
export async function duplicateDraft(draftId) {
  const res = await fetch(`${API_URL}/notas/drafts/${draftId}/duplicate`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${localStorage.getItem("accessToken")}`,
      "Content-Type": "application/json"
    }
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Falha ao duplicar rascunho");
  }
  return res.json();
}
export async function draftsReconcile({ emitterId, preview_batch_id, keep_indices, group_indices }) {
  const res = await apiClient.post('/notas/drafts/reconcile', {
    emitterId,
    preview_batch_id,
    keep_indices,
    group_indices,
  });
  return res.data;
}

/* =======================
 * TASKS
 * ======================= */
export async function getTasks({ emitterId, status, mes, ano } = {}) {
  const response = await apiClient.get('/tasks', { params: { emitterId, status, mes, ano } });
  return response.data;
}

export async function getResumo(mes, ano) {
  const response = await apiClient.get('/tasks/resumo', { params: { mes, ano } });
  return response.data;
}

export async function sendEmail(taskId) {
  const response = await apiClient.post(`/tasks/${taskId}/email`);
  return response.data;
}

export const deleteTask = (taskId) => {
 return apiClient.delete(`/tasks/${taskId}`);
};

/**
 * Envia uma solicitação de cancelamento para uma task (nota) específica.
 * @param {string} taskId - O ID da task (nota) a ser cancelada.
 * @param {string} justificativa - O motivo do cancelamento (mín. 15 caracteres).
 */
export const cancelTask = (taskId, justificativa, cMotivo) => {
  return apiClient.post(`/notas/cancelar/${taskId}`, {
    justificativa,
    cMotivo
  });
};

/**
 * Envia uma solicitação de cancelamento em LOTE.
 * O backend irá iterar e cancelar uma por uma.
 * @param {object} payload - O objeto { task_ids: string[], justificativa: string }
 */
export const cancelTasksBatch = async (payload) => {
  // payload é { task_ids: [...], justificativa: "..." }
  // O frontend espera o .data de volta (com {sucessos, falhas}), por isso o await/return
  const response = await apiClient.post('/notas/cancelar-lote', payload);
  return response.data;
};

/* =======================
 * DOWNLOADS
 * ======================= */
export async function downloadXml(taskId) {
  const res = await apiClient.get(`/tasks/${taskId}/xml`, { responseType: 'blob' });
  const blob = new Blob([res.data], { type: res.headers['content-type'] || 'application/xml' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.download = pickFileName(res.headers['content-disposition'], `nfse_${taskId}.xml`);
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function downloadGuia(taskId) {
  const res = await apiClient.get(`/tasks/${taskId}/guia`, { responseType: 'blob' });
  const blob = new Blob([res.data], { type: res.headers['content-type'] || 'application/pdf' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.download = pickFileName(res.headers['content-disposition'], `danfs_${taskId}.pdf`);
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function downloadAllXml({ emitterId, mes, ano, task_ids } = {}) {
  const params = new URLSearchParams();

  if (emitterId) params.append('emitterId', emitterId);
  if (mes !== undefined) params.append('mes', mes);
  if (ano !== undefined) params.append('ano', ano);

  if (task_ids && Array.isArray(task_ids)) {
    task_ids.forEach(id => params.append('task_ids', id));
  }

  const res = await apiClient.get('/tasks/batch/xml', {
    params: params,
    responseType: 'blob',
  });

  const blob = new Blob(
    [res.data],
    { type: res.headers['content-type'] || 'application/zip' }
  );

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.download = pickFileName(
    res.headers['content-disposition'],
    'xml.zip'
  );
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function downloadAllPdf({ emitterId, mes, ano, task_ids } = {}) {
  const params = new URLSearchParams();

  if (emitterId) params.append('emitterId', emitterId);
  if (mes !== undefined) params.append('mes', mes);
  if (ano !== undefined) params.append('ano', ano);

  if (task_ids && Array.isArray(task_ids)) {
      task_ids.forEach(id => params.append('task_ids', id));
  }

  const res = await apiClient.get('/tasks/batch/pdf', {
    params: params,
    responseType: 'blob',
  });

  const blob = new Blob(
    [res.data],
    { type: res.headers['content-type'] || 'application/zip' }
  );

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.download = pickFileName(
    res.headers['content-disposition'],
    'danfs.zip'
  );
  a.href = url;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function exportTasksXlsx({ mes, ano, emitterId } = {}) {
  const params = {};
  if (mes) params.mes = mes;
  if (ano) params.ano = ano;
  if (emitterId) params.emitterId = emitterId;

  try {
    const res = await apiClient.get('/tasks/export', {
      params,
      responseType: 'blob',
    });

    const blob = new Blob(
      [res.data],
      { type: res.headers['content-type'] || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }
    );

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');

    // 1. Tenta pegar o nome do arquivo do header enviado pelo backend
    let filename = null;
    const disposition = res.headers['content-disposition'];

    if (disposition && disposition.includes('filename=')) {
       // Regex para extrair o conteúdo limpo dentro ou fora de aspas
       // Ex: attachment; filename="nfse_112025.xlsx" -> nfse_112025.xlsx
       const match = disposition.match(/filename=["']?([^;"']+)["']?/);
       if (match && match[1]) {
           filename = match[1];
       }
    }

    // 2. Fallback: Se falhar o header (ex: CORS), monta o nome manualmente igual ao backend
    if (!filename) {
        const mesStr = mes ? String(mes).padStart(2, '0') : '00';
        filename = `nfse_${mesStr}${ano || '0000'}.xlsx`;
    }

    a.download = filename;
    a.href = url;

    document.body.appendChild(a);
    a.click();
    a.remove();

    window.URL.revokeObjectURL(url);

  } catch (error) {
    console.error("Erro no download da planilha:", error);
    // Opcional: mostrar toast/alerta de erro aqui
  }
}

/* =======================
 * USUÁRIO
 * ======================= */
export async function getMe() {
  const response = await apiClient.get('/auth/users/me');
  if (response.data) {
    localStorage.setItem('user', JSON.stringify(response.data));
  }
  return response.data;
}

/* =======================
 * ALÍQUOTA (PGDAS)
 * ======================= */
export async function processarPGDAS(emitterId, file) {
  const fd = new FormData();
  fd.append("emitterId", emitterId);
  fd.append("file", file);

  const response = await apiClient.post("/aliquota/processar", fd);
  return response.data;
}

export async function getAliquotasAtuais() {
  const response = await apiClient.get("/aliquota/atuais");
  return response.data;
}

export async function getAliquotaAtual(emitterId) {
  const response = await apiClient.get(`/aliquota/atual/${emitterId}`);
  return response.data;
}


export { apiClient };
