from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Body, Depends, Path
from typing import Optional, Dict, Any, Tuple, List
from bson import ObjectId
import pandas as pd
from datetime import datetime
import logging
import re
import io
from pydantic import BaseModel, Field
from db import db
from models import UserInDB
from routers.auth import get_current_user
from utils import (
    to_float,
    next_dps,
    canonical_from_label,
    gerar_dpsXmlGZipB64,
    parse_nfse_response,
    sanitize_document,
    is_dps_repetida
)
from backend.transmitter import enviar_nfse_pkcs12, enviar_cancelamento_pkcs12
from backend.nfse_builder import build_nfse_xml, build_cancelamento_xml
from backend.signer import assinar_xml

router = APIRouter(prefix="/notas", tags=["Notas"])
log = logging.getLogger("uvicorn.error")


# --- Models Pydantic para Payloads de Cancelamento ---
class CancelamentoPayload(BaseModel):
    justificativa: str = Field(..., min_length=15, description="Justificativa (mín. 15 caracteres)")
    cMotivo: str = Field(..., regex="^(1|2|9)$", description="1=Erro, 2=Não prestado, 9=Outros")


class CancelamentoLotePayload(BaseModel):
    task_ids: List[str] = Field(..., min_length=1)
    justificativa: str = Field(..., min_length=15)
    cMotivo: str = Field(..., regex="^(1|2|9)$")


# --- Funções Auxiliares  ---
def _ctn_to_6digits(cod: Optional[str]) -> Optional[str]:
    if not cod: return None
    s = str(cod).strip()
    if " - " in s: s = s.split(" - ", 1)[0].strip()
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,2})$", s)
    if m: a, b, c = m.groups(); return f"{a.zfill(2)}{b.zfill(2)}{c.zfill(2)}"
    digits = re.sub(r"\D", "", s)
    if len(digits) == 5: digits = "0" + digits
    return digits if len(digits) == 6 else None


def _normalize_competencia(raw: Optional[str], fallback_today: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """
    Converte uma string de data (qualquer formato) para AAAA-MM-DD e AAAA-MM.
    É robusto e valida a data.
    """
    s = str(raw).strip() if raw else None

    if s:
        # --- 1. Tenta formato ISO (AAAA-MM-DDThh:mm:ss...) ---
        if 'T' in s and len(s) > 10:
            s = s.split('T')[0]  # Pega só o AAAA-MM-DD

        # --- 2. Tenta formatos de data completa (prioriza AAAA-MM-DD) ---
        for fmt in ["%Y-%m-%d", "%d/%m/%Y"]:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m")
            except ValueError:
                continue  # Tenta o próximo formato

    # --- Se 'raw' for None ou nenhum formato for válido, usa o fallback ---
    if fallback_today:
        today = datetime.utcnow()
        # Retorna o primeiro dia do MÊS ATUAL
        return today.strftime("%Y-%m-01"), today.strftime("%Y-%m")

    return None, None


# --- FUNÇÃO HELPER DE CANCELAMENTO ---
def _processar_cancelamento_task(task_id: str, justificativa: str, c_motivo: str, user_id: ObjectId, db: Any) -> Tuple[bool, str, Optional[Dict]]:
    """
    Lógica de negócio para processar um único cancelamento.
    Retorna (Sucesso, Mensagem, Resposta_API_JSON)
    """
    log.info(f"[Cancelamento] Processando task: {task_id} para User: {user_id}")
    task_query = {"_id": ObjectId(task_id), "user_id": user_id}

    try:
        task = db.tasks.find_one(task_query)

        if not task:
            return (False, "Nota (Task) não encontrada", None)
        if task.get("status") != "accepted":
            return (False, "Apenas notas 'accepted' podem ser canceladas", None)

        transmit_data = task.get("transmit") or {}
        chave_acesso = transmit_data.get("chave_acesso")
        if not chave_acesso:
            return (False, "Task não possui Chave de Acesso", None)

        emitter = db.emitters.find_one({"_id": ObjectId(task["emitter_id"]), "user_id": user_id})
        if not emitter:
            return (False, "Emissor não encontrado", None)

        emitter_cnpj = sanitize_document(emitter.get("cnpj") or emitter.get("cpf"))
        pfx_path = emitter.get("certificado_path")
        pfx_pwd = emitter.get("senha_certificado")

        if not all([emitter_cnpj, pfx_path, pfx_pwd]):
            return (False, "Emissor sem CNPJ, certificado ou senha", None)

        # 1. Montar XML de Cancelamento
        xml_cancelamento = build_cancelamento_xml(
            emitter_cnpj=emitter_cnpj,
            chave_acesso_nota=chave_acesso,
            justificativa=justificativa,
            c_motivo=c_motivo
        )

        print("\n==== XML DE CANCELAMENTO (SEM ASSINAR) ====\n")
        print(xml_cancelamento)
        print("\n==========================================\n")

        xml_assinado = assinar_xml(
            xml_cancelamento,
            pfx_path=pfx_path,
            pfx_password=pfx_pwd,
            tag_to_sign="infPedReg"
        )

        # 3. Comprimir e Encodar (reutilizando sua função)
        evento_b64_gzip = gerar_dpsXmlGZipB64(xml_assinado)

        # 4. Transmitir
        resp = enviar_cancelamento_pkcs12(
            chave_acesso=chave_acesso,
            evento_b64_gzip=evento_b64_gzip,
            pfx_path=pfx_path,
            pfx_password=pfx_pwd
        )

        http_status = resp.status_code
        raw_resp = resp.text

        try:
            json_resp = resp.json()
        except Exception:
            json_resp = {"raw": raw_resp}

        # 5. Tratar Resposta
        if http_status in (200, 201):
            update_set = {
                "status": "canceled",
                "canceled_at": datetime.utcnow(),
                "cancel_event": {"sent_at": datetime.utcnow(), "http_status": http_status, "response": json_resp}
            }
            db.tasks.update_one(task_query, {"$set": update_set})

            msg_sucesso = (json_resp.get("retornoEvento") or [{}])[0].get("xMotivo", "Cancelamento registrado")
            return (True, msg_sucesso, json_resp)
        else:
            log.warning(f"[Cancelamento] API Rejeitou {task_id}: HTTP {http_status} | {raw_resp}")
            return (False, f"API Rejeitou: {raw_resp}", json_resp)

    except Exception as e:
        log.error(f"[Cancelamento] Falha Crítica {task_id}: {e}", exc_info=True)
        # Garante que o DB não fique em estado inconsistente se a falha for local
        db.tasks.update_one(task_query, {"$set": {"status": "error", "error_at": datetime.utcnow(),
                                                  "transmit.error": f"Falha no cancelamento: {e}"}})
        return (False, f"Exceção no backend: {e}", None)


# --- Endpoints de Emissão  ---
@router.post("/confirmar-from-drafts")
def notas_confirmar_from_drafts(payload: Dict[str, Any] = Body(...),
                                current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    emitter_id = payload.get("emitterId")
    draft_ids = payload.get("draftIds") or []
    client_ids = payload.get("clientIds") or []

    if not emitter_id: raise HTTPException(status_code=400, detail="emitterId é obrigatório")
    if not draft_ids and not client_ids: raise HTTPException(status_code=400, detail="Informe draftIds ou clientIds")

    emitter_query = {"_id": ObjectId(emitter_id), "user_id": user_id}
    emitter = db.emitters.find_one(emitter_query)
    if not emitter:
        raise HTTPException(status_code=404, detail="Emissor não encontrado ou não pertence ao seu usuário")
    if not emitter.get("certificado_path"): raise HTTPException(status_code=400, detail="Emissor sem certificado")

    drafts_to_emit = []
    draft_query = {"emitter_id": emitter_id, "status": "pending", "user_id": user_id}
    if draft_ids:
        oids = [ObjectId(d) for d in draft_ids if ObjectId.is_valid(d)]
        if oids:
            cursor = db.tasks_draft.find({**draft_query, "_id": {"$in": oids}})
            drafts_to_emit.extend(list(cursor))
    if client_ids:
        for cid in client_ids:
            cursor = db.tasks_draft.find({**draft_query, "client_id": cid}).sort([("competencia_month", 1)])
            drafts_to_emit.extend(list(cursor))

    # ? Busca a alíquota atual do emissor
    aliquota_doc = db.aliquotas.find_one(
        {"emitter_id": ObjectId(emitter_id)},
        sort=[("ano", -1), ("mes", -1), ("created_at", -1)]
    )
    if not aliquota_doc:
        raise HTTPException(status_code=404, detail="Nenhuma alíquota registrada para este emissor.")
    aliquota_atual = float(aliquota_doc.get("aliquota") or 0)

    # Deduplicar
    seen, unique = set(), []
    for d in drafts_to_emit:
        if str(d["_id"]) not in seen:
            seen.add(str(d["_id"]))
            unique.append(d)
    drafts_to_emit = unique

    if not drafts_to_emit: raise HTTPException(status_code=404, detail="Nenhum rascunho 'pending' encontrado")

    created, task_ids, erros = 0, [], []
    for d in drafts_to_emit:
        try:
            client_id = d.get("client_id")
            if not client_id:
                raise ValueError("Draft sem client_id")

            # --- ? Busca o cliente, aceitando string ou ObjectId ---
            try:
                client = db.clients.find_one({"_id": ObjectId(client_id), "user_id": user_id})
            except Exception:
                client = db.clients.find_one({"_id": client_id, "user_id": user_id})

            if not client:
                # tenta localizar o "tomador não identificado"
                client = db.clients.find_one({
                    "nao_identificado": True,
                    "emissores_ids": emitter_id,
                    "user_id": user_id
                })
            if not client:
                raise ValueError("Cliente não encontrado")

            # --- ? CTN fallback ---
            ctn6 = _ctn_to_6digits(d.get("cod_servico")) or "010101"

            # --- ? Dados do serviço ---
            service_data = {
                "descricao": d["descricao"],
                "valor": float(d.get("valor") or 0),
                "cTribNac": ctn6,
                "aliquota": aliquota_atual,
                "municipioIbge": d.get("municipio_ibge"),
                "issRetido": d.get("iss_retido"),
            }

            # --- ? Gera o XML e assina ---
            dps = next_dps(db, emitter_id, serie="1")
            competencia_raw = d.get("competencia") or d.get("dataEmissao")
            competencia_formatada, _ = _normalize_competencia(competencia_raw, fallback_today=True)
            xml = build_nfse_xml(
                emitter, client, service_data,
                numero_dps=dps["numero"], serie_dps=dps["serie"],
                competencia=competencia_formatada,
                data_emissao=d.get("dataEmissao")
            )

            pfx_pwd = emitter.get("senha_certificado") or ""
            xml_signed = assinar_xml(xml, pfx_path=emitter["certificado_path"], pfx_password=pfx_pwd)

            # --- ? Cria a task ---
            task = {
                "user_id": user_id,
                "type": "emit_nfse",
                "emitter_id": emitter_id,
                "client_id": str(client["_id"]),
                "valor": float(d.get("valor") or 0),
                "status": "pending",
                "created_at": datetime.utcnow(),
                "dps": {"serie": dps["serie"], "numero": dps["numero"], "status": "reservado"},
                "competencia": competencia_formatada,
                "response": {"xml": xml_signed, "valor": float(d.get("valor") or 0)},
                "source": {"kind": "draft", "draft_id": str(d["_id"])},
            }

            res = db.tasks.insert_one(task)
            task_id = str(res.inserted_id)
            task_ids.append(task_id)
            created += 1

            # --- ? Marca o draft como consumido ---
            db.tasks_draft.update_one(
                {"_id": d["_id"]},
                {"$set": {"status": "consumed", "consumed_at": datetime.utcnow(), "task_id": task_id}}
            )


        except Exception as e:
            import traceback
            log.error(f"Erro ao gerar task do draft {d.get('_id')}: {e}")
            log.error(traceback.format_exc())
            erros.append({"draft_id": str(d.get("_id")), "erro": str(e)})

    if created == 1:
        msg = "1 solicitação criada com sucesso"
    else:
        msg = f"{created} solicitações criadas com sucesso"

    return {"msg": msg, "task_ids": task_ids, "erros": erros}


@router.post("/preview")
async def notas_preview(emitterId: str = Form(...), competenciaDefault: Optional[str] = Form(None),
                        file: UploadFile = File(...), persist: Optional[str] = Form("1"),
                        current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    emitter = db.emitters.find_one({"_id": ObjectId(emitterId), "user_id": user_id})
    if not emitter:
        raise HTTPException(status_code=404, detail="Emissor não encontrado ou não pertence ao seu usuário")

    # --- ? Busca a alíquota mais recente no banco ---
    aliquota_doc = db.aliquotas.find_one(
        {"emitter_id": ObjectId(emitterId)},
        sort=[("ano", -1), ("mes", -1), ("created_at", -1)]
    )
    if not aliquota_doc:
        raise HTTPException(status_code=404, detail="Nenhuma alíquota registrada para este emissor.")
    aliquota_padrao = float(aliquota_doc.get("aliquota") or 0)

    preview_batch_id = str(ObjectId())

    # --- ? Detecta o tipo de arquivo (planilha x JSON manual) ---
    content = await file.read()
    filename = file.filename.lower()

    if filename.endswith(".json"):
        try:
            import json
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, list):
                data = [data]  # garante lista única
            df = pd.DataFrame(data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro lendo JSON: {e}")
    else:
        try:
            if filename.endswith(".xlsx"):
                df = pd.read_excel(io.BytesIO(content), dtype=str)
            else:
                df = pd.read_csv(io.BytesIO(content), dtype=str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro lendo planilha: {e}")

    persist_flag = str(persist).strip().lower() not in ("0", "false", "no", "n")

    # --- ? Normalização das colunas ---
    df = df.rename(columns={c: canonical_from_label(c) for c in df.columns}).fillna("").reset_index(drop=True)

    if not all(c in df.columns for c in ["cpf_cnpj", "valor", "descricao"]):
        raise HTTPException(status_code=400, detail="Colunas obrigatórias ausentes: cpf_cnpj, valor, descricao")

    linhas = []
    for idx, row in df.iterrows():
        erros = []
        doc_digits = sanitize_document(row.get("cpf_cnpj"))

        cliente = None
        if doc_digits:
            if len(doc_digits) == 11:
                cliente = db.clients.find_one({
                    "cpf": doc_digits,
                    "user_id": user_id,
                    "ativo": {"$ne": False}
                })
            elif len(doc_digits) == 14:
                cliente = db.clients.find_one({
                    "cnpj": doc_digits,
                    "user_id": user_id,
                    "ativo": {"$ne": False}
                })

        if not cliente and not doc_digits:
            cliente = db.clients.find_one({"nao_identificado": True, "emissores_ids": emitterId, "user_id": user_id})
        elif not cliente:
            erros.append("Cliente não encontrado ou está inativo")

        valor = to_float(row.get("valor"))
        if not valor or valor <= 0:
            erros.append("Valor inválido")
        if not row.get("descricao"):
            erros.append("Descrição obrigatória")

        linha = {
            "index": idx + 2,
            "ok": len(erros) == 0,
            "erros": erros,
            "clienteId": str(cliente["_id"]) if cliente else None,
            **row.to_dict(),
        }
        linhas.append(linha)

    # ? Se for JSON (input manual) e linha válida ? salva automaticamente no tasks_draft
    if filename.endswith(".json") and persist_flag:
        validas = [l for l in linhas if l["ok"] and l.get("clienteId")]
        for l in validas:
            # 1. Prioriza a data de emissão exata vinda do modal (manual.json)
            data_emissao_iso = l.get("dataemissao")

            # 2. Se ela veio, extrai a competência (YYYY-MM-DD e YYYY-MM) a partir dela
            if data_emissao_iso:
                try:
                    # Extrai a data (ex: "2025-11-10") da string ISO
                    date_str = data_emissao_iso.split("T")[0]
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    comp_full = dt.strftime("%Y-%m-%d")
                    comp_month = dt.strftime("%Y-%m")
                except Exception:
                    # Fallback se a dataEmissao for inválida
                    data_emissao_iso = None
                    comp_full, comp_month = _normalize_competencia(None, fallback_today=True)

            # 3. Se dataEmissao NÃO VEIO (fallback, improvável), usa a lógica antiga
            else:
                comp_raw = l.get("competencia") or competenciaDefault
                comp_full, comp_month = _normalize_competencia(comp_raw, fallback_today=True)
                data_emissao_iso = f"{comp_full}T00:00:00-03:00" if comp_full else None

            uniq_key = f"{emitterId}:{l['clienteId']}:{comp_month}"

            draft_doc = {
                "user_id": user_id,
                "status": "pending",
                "emitter_id": emitterId,
                "client_id": l["clienteId"],
                "cpf_cnpj": l["cpf_cnpj"],
                "cliente_nome": l.get("cliente_nome"),
                "descricao": l["descricao"],
                "valor": float(l["valor"]),
                "competencia": comp_full,
                "competencia_month": comp_month,
                "dataEmissao": data_emissao_iso,
                "uniq_key": uniq_key,
                "cod_servico": l.get("cod_servico") or "01.01.01",
                "aliquota": aliquota_padrao,
                "municipio_ibge": l.get("municipio_ibge"),
                "pais_prestacao": l.get("pais_prestacao") or "BRASIL",
                "iss_retido": l.get("iss_retido") or False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "origem": "manual",
            }
            db.tasks_draft.update_one(
                {"uniq_key": uniq_key, "user_id": user_id, "status": "pending"},
                {"$set": draft_doc},
                upsert=True
            )

    # ? Se for planilha (XLSX/CSV) e linha válida ? também salva automaticamente nos drafts
    if not filename.endswith(".json"):
        todas = [l for l in linhas if l.get("clienteId")]
        for l in todas:
            # competência: usa a da linha ou o default do form
            comp_raw = l.get("dataemissao") or l.get("competencia") or competenciaDefault
            comp_full, comp_month = _normalize_competencia(comp_raw)
            data_emissao_iso = f"{comp_full}T00:00:00-03:00" if comp_full else None

            # status/erros conforme validação da linha
            is_ok = bool(l.get("ok"))
            status = "pending" if is_ok else "invalid"
            erros = [] if is_ok else ["Erro"]

            # chave de rascunho do preview (inclui descr/valor p/ distinguir linhas iguais)
            uniq_key = f"{emitterId}:{l['clienteId']}:{comp_month}:{hash(l['descricao'])}:{l.get('valor')}"

            draft_doc = {
                "user_id": user_id,
                "status": status,  # <- pending ou invalid
                "emitter_id": emitterId,
                "client_id": l["clienteId"],
                "cpf_cnpj": l["cpf_cnpj"],
                "cliente_nome": l.get("cliente_nome"),
                "descricao": l["descricao"],
                "valor": float(l["valor"]) if l.get("valor") not in (None, "",) else 0.0,
                "competencia": comp_full,
                "competencia_month": comp_month,
                "dataEmissao": data_emissao_iso,
                "uniq_key": uniq_key,
                "cod_servico": l.get("cod_servico") or "01.01.01",
                "aliquota": aliquota_padrao,
                "municipio_ibge": cliente.get("codigoIbge") if cliente else None,
                "pais_prestacao": l.get("pais_prestacao") or "BRASIL",
                "iss_retido": l.get("iss_retido") or False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),

                # extras úteis
                "ok": is_ok,
                "erros": erros,

                # ? metadados p/ reconcile
                "origem": {
                    "tipo": "planilha",
                    "preview_id": preview_batch_id,  # <- importante!
                    "preview_index": l.get("index"),  # índice da linha exibido no modal
                },
            }

            # upsert p/ manter idempotência dentro do preview
            db.tasks_draft.update_one(
                {"uniq_key": uniq_key, "user_id": user_id, "status": status},
                {"$set": draft_doc},
                upsert=True
            )

    return {
        "linhas": linhas,
        "validas": sum(1 for l in linhas if l.get("ok")),
        "invalidas": sum(1 for l in linhas if not l.get("ok")),
        "preview_batch_id": preview_batch_id,  # <- devolve para o front
    }


@router.post("/confirmar")
def notas_confirmar(payload: dict = Body(...), current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    emitter_id = payload.get("emitterId")
    items = payload.get("items") or []
    if not emitter_id or not items: raise HTTPException(status_code=400, detail="emitterId e items são obrigatórios")

    emitter = db.emitters.find_one({"_id": ObjectId(emitter_id), "user_id": user_id})
    if not emitter:
        raise HTTPException(status_code=404, detail="Emissor não encontrado ou não pertence ao seu usuário")
    if not emitter.get("certificado_path"): raise HTTPException(status_code=400, detail="Emissor sem certificado")

    created, task_ids, erros = 0, [], []
    for it in items:
        try:
            if not it.get("ok"): raise ValueError("Linha inválida na prévia")

            client = db.clients.find_one({"_id": ObjectId(it["clienteId"]), "user_id": user_id})
            if not client:
                raise ValueError("Cliente não encontrado ou não pertence ao seu usuário")
            service_data = {
                "descricao": it["descricao"], "valor": float(it["valor"]), "cTribNac": it["cod_servico"],
                "aliquota": it["aliquota"], "municipioIbge": it.get("municipio_ibge"),
                "issRetido": it.get("iss_retido"),
            }

            dps = next_dps(db, emitter_id, serie="U")
            xml = build_nfse_xml(
                emitter, client, service_data,
                numero_dps=dps["numero"], serie_dps=dps["serie"],
                competencia=it["competencia"],
                data_emissao=it.get("dataEmissao")
            )

            pfx_pwd = emitter.get("senha_certificado") or ""
            xml_signed = assinar_xml(xml, pfx_path=emitter["certificado_path"], pfx_password=pfx_pwd)

            task = {
                "user_id": user_id, "type": "emit_nfse", "emitter_id": emitter_id, "client_id": it["clienteId"],
                "valor": float(it["valor"]), "status": "pending", "created_at": datetime.utcnow(),
                "dps": {"serie": dps["serie"], "numero": dps["numero"], "status": "reservado"},
                "competencia": it["competencia"],
                "response": {"xml": xml_signed, "valor": float(it["valor"])},
            }
            res = db.tasks.insert_one(task)
            task_ids.append(str(res.inserted_id))
            created += 1
        except Exception as e:
            erros.append({"index": it.get("index"), "erro": str(e)})

    if created == 1:
        msg = "1 solicitação criada com sucesso"
    else:
        msg = f"{created} solicitações criadas com sucesso"

    return {"msg": msg, "task_ids": task_ids, "erros": erros}


@router.post("/enviar/{task_id}")
def notas_enviar_task(task_id: str = Path(...), current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    task_query = {"_id": ObjectId(task_id), "user_id": user_id}
    task = db.tasks.find_one(task_query)

    if not task:
        raise HTTPException(status_code=404, detail="Task não encontrada ou não pertence ao seu usuário")
    if task.get("status") not in ("pending", "error"):
        raise HTTPException(
            status_code=400,
            detail="Status atual não permite envio"
        )

    emitter = db.emitters.find_one({"_id": ObjectId(task["emitter_id"]), "user_id": user_id})
    if not emitter:
        raise HTTPException(status_code=404,
                            detail="Emissor associado à task não encontrado ou não pertence ao seu usuário")

    xml_assinado = (task.get("response") or {}).get("xml")
    if not xml_assinado: raise HTTPException(status_code=400, detail="Task sem XML assinado")

    dps_b64 = gerar_dpsXmlGZipB64(xml_assinado)
    pfx_pwd = emitter.get("senha_certificado") or ""

    try:
        resp = enviar_nfse_pkcs12(dps_b64, emitter["certificado_path"], pfx_pwd)
        raw_resp = resp.get("body", "")
        status_code = resp.get("status", 0)

        # preferir o XML final (descompactado) quando existir
        xml_nfse = resp.get("xml_nfse")
        pdf_base64 = resp.get("pdf_base64")
        id_dps = resp.get("id_dps")
        chave_acesso = resp.get("chave_acesso")

        # 1) parse (prefere XML final) + fallback da chave de acesso
        receipt = parse_nfse_response(xml_nfse) if xml_nfse else parse_nfse_response(raw_resp)

        # Se não veio numero_nfse mas veio chaveAcesso, usa-a
        if not receipt.get("numero_nfse") and chave_acesso:
            receipt["numero_nfse"] = str(chave_acesso)

        # Se a prefeitura respondeu 200/201 e temos XML final OU chave, isso é sucesso (desde que não haja erros)
        if status_code in (200, 201) and (xml_nfse or chave_acesso) and not receipt.get("erros"):
            receipt["success"] = True

        # 2) decide status com base nessa consolidação
        if is_dps_repetida(receipt):
            new_status = "retry_dps"
        else:
            new_status = "accepted" if (
                    status_code in (200, 201)
                    and (receipt.get("success") or xml_nfse or chave_acesso)
            ) else "error"

        update_set = {
            "status": new_status,
            "sent_at": datetime.utcnow(),
            "transmit": {
                "http_status": status_code,
                "raw_response": raw_resp,
                "receipt": receipt,
                "xml_nfse": xml_nfse,
                "pdf_base64": pdf_base64,
                "id_dps": id_dps,
                "chave_acesso": chave_acesso,
            }
        }
        db.tasks.update_one(task_query, {"$set": update_set})

        if new_status == "error":
            raise HTTPException(status_code=502, detail=f"Falha na transmissão: {receipt.get('mensagem') or raw_resp}")

        if new_status == "retry_dps":
            return {"msg": "DPS já utilizada ? marcada como retry_dps", "status": "retry_dps"}

        return {"msg": "Transmitido", "status": new_status, "receipt": receipt}

    except Exception as e:
        db.tasks.update_one(task_query,
                            {"$set": {"status": "error", "error_at": datetime.utcnow(), "transmit": {"error": str(e)}}})
        raise HTTPException(status_code=502, detail=f"Falha ao transmitir: {e}")


# --- NOVOS ENDPOINTS DE CANCELAMENTO ---
@router.post("/cancelar/{task_id}")
def notas_cancelar_task(
        task_id: str = Path(...),
        payload: CancelamentoPayload = Body(...),
        current_user: UserInDB = Depends(get_current_user)
):
    """Cancela uma única nota fiscal (task) 'accepted'."""
    user_id = ObjectId(current_user.id)

    sucesso, msg, json_resp = _processar_cancelamento_task(
        task_id=task_id,
        justificativa=payload.justificativa,
        c_motivo=payload.cMotivo,
        user_id=user_id,
        db=db
    )

    if sucesso:
        return {"msg": "Nota cancelada com sucesso", "status": "canceled", "response": msg}
    else:
        # Se falhou, decide o status code
        status_code = 400 if "API Rejeitou" in msg or "Apenas notas" in msg else 500
        raise HTTPException(status_code=status_code, detail=msg)


@router.post("/cancelar-lote")
def notas_cancelar_lote(
        payload: CancelamentoLotePayload = Body(...),
        current_user: UserInDB = Depends(get_current_user)
):
    """Cancela uma lista de notas (tasks) 'accepted', uma a uma."""
    user_id = ObjectId(current_user.id)
    sucessos = 0
    falhas = 0

    # Processa um por um, exatamente como você sugeriu
    for task_id in payload.task_ids:
        try:
            sucesso, msg, _ = _processar_cancelamento_task(
                task_id=task_id,
                justificativa=payload.justificativa,
                c_motivo=payload.cMotivo,
                user_id=user_id,
                db=db
            )
            if sucesso:
                sucessos += 1
            else:
                log.warning(f"Falha no lote (Task {task_id}): {msg}")
                falhas += 1
        except Exception as e:
            # Captura exceção inesperada no loop
            log.error(f"Erro grave no loop de lote (Task {task_id}): {e}", exc_info=True)
            falhas += 1

    return {
        "msg": f"Processamento em lote concluído.",
        "sucessos": sucessos,
        "falhas": falhas
    }
