from fastapi import APIRouter, HTTPException, Body, Depends
from typing import Optional, Dict, Any
from bson import ObjectId
from datetime import datetime
from db import db
from models import NotaPreviewItemIn, TaskDraftUpdate, UserInDB
from utils import serialize_doc
from routers.auth import get_current_user
import re

router = APIRouter(prefix="/notas/drafts", tags=["Drafts"])


def _proj(d):
    return serialize_doc(d)


@router.post("/import")
def drafts_import(payload: Dict[str, Any] = Body(...), current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    emitterId = payload.get("emitterId")
    items = payload.get("items") or []

    if not emitterId:
        raise HTTPException(status_code=400, detail="emitterId é obrigatório")

    emitter_query = {"_id": ObjectId(emitterId), "user_id": user_id}
    if not db.emitters.find_one(emitter_query):
        raise HTTPException(status_code=404, detail="Emissor não encontrado ou não pertence ao seu usuário")

    # --- REMOVIDO: A busca global da alíquota aqui estava errada ---

    created, updated, skipped, draft_ids = 0, 0, 0, []

    # Cache local para não consultar o banco mil vezes no mesmo loop
    # Chave: "2025-11", Valor: 0.1162 (float)
    rates_cache = {}

    def _competencia_month(s: Optional[str]) -> Optional[str]:
        if not s: return None
        s = str(s).strip()
        # Aceita YYYY-MM-DD ou YYYY-MM
        m = re.match(r"^(\d{4}-\d{2})", s)
        return m.group(1) if m else None

    # Função auxiliar para buscar alíquota correta por mês
    def get_rate_for_month(comp_str):
        if not comp_str: return 0.0
        if comp_str in rates_cache:
            return rates_cache[comp_str]

        try:
            ano, mes = map(int, comp_str.split('-'))
            # Busca EXATA para aquele mês/ano
            doc = db.aliquotas.find_one({
                "emitter_id": ObjectId(emitterId),
                "mes": mes,
                "ano": ano
            })

            if doc:
                val = float(doc.get("aliquota") or 0)
            else:
                # FALLBACK: Se não achar a do mês específico, pega a última disponível ANTERIOR ou IGUAL a data
                # Isso evita pegar alíquota de Dezembro para nota de Novembro
                # Mas o ideal é ter a alíquota exata.
                fallback = db.aliquotas.find_one(
                    {
                        "emitter_id": ObjectId(emitterId),
                        "$or": [
                            {"ano": {"$lt": ano}},
                            {"ano": ano, "mes": {"$lte": mes}}
                        ]
                    },
                    sort=[("ano", -1), ("mes", -1)]
                )
                val = float(fallback.get("aliquota") or 0) if fallback else 0.0

            rates_cache[comp_str] = val
            return val
        except:
            return 0.0

    for raw in items:
        try:
            force_new = bool(raw.get("force_new") or raw.get("duplicate_confirmed"))
            cleaned = dict(raw)
            cleaned.pop("force_new", None)
            cleaned.pop("duplicate_confirmed", None)

            item = NotaPreviewItemIn(**cleaned)
            if not item.ok:
                skipped += 1
                continue

            cliente = db.clients.find_one({
                "_id": ObjectId(item.clienteId),
                "user_id": user_id,
                "ativo": {"$ne": False}
            })
            if not cliente:
                skipped += 1
                continue

            comp_month = _competencia_month(item.competencia)
            if not comp_month:
                skipped += 1
                continue

            # --- BUSCA ALIQUOTA ---
            aliquota_item = get_rate_for_month(comp_month)
            # -------------------------------------------------------------------------------
            # TRAVA DE SEGURANÇA: Se não tiver alíquota, bloqueia a criação/importação

            if aliquota_item <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"ERRO: Não foi encontrada alíquota (PGDAS) para a competência {comp_month}. "
                           f"Por favor, vá em 'Alíquotas' e faça o upload do PGDAS correspondente antes de emitir a nota."
                )

            uniq_key = f"{emitterId}:{item.clienteId}:{comp_month}"

            doc = {
                "user_id": user_id,
                "status": "pending",
                "emitter_id": emitterId,
                "client_id": item.clienteId,
                "cpf_cnpj": item.cpf_cnpj,
                "cliente_nome": item.cliente_nome,
                "descricao": item.descricao,
                "valor": float(item.valor),
                "competencia": item.competencia,
                "competencia_month": comp_month,
                "uniq_key": uniq_key,
                "cod_servico": item.cod_servico,
                "aliquota": aliquota_item,  # Usa a alíquota correta do mês
                "municipio_ibge": item.municipio_ibge,
                "pais_prestacao": item.pais_prestacao,
                "iss_retido": item.iss_retido,
                "dataEmissao": item.dataEmissao,
                "duplicate_confirmed": force_new,
                "updated_at": datetime.utcnow(),
                "origem": cleaned.get("origem") or raw.get("origem"),
            }

            find_query = {
                "user_id": user_id,
                "emitter_id": emitterId,
                "client_id": item.clienteId,
                "competencia_month": comp_month,
                "status": "pending"
            }

            if force_new:
                existing_group = list(db.tasks_draft.find(find_query))
                group_id = existing_group[0].get("duplicate_group_id") if existing_group else uniq_key
                next_seq = (max([e.get("seq", 0) for e in existing_group]) if existing_group else 0) + 1
                doc["uniq_key"] = f"{uniq_key}:{next_seq}"
                doc.update({"duplicate_group_id": group_id, "seq": next_seq, "created_at": datetime.utcnow()})
                res = db.tasks_draft.insert_one(doc)
                draft_ids.append(str(res.inserted_id))
                created += 1
            else:
                existing = db.tasks_draft.find_one(find_query, sort=[("updated_at", -1)])
                if existing:
                    if existing.get("duplicate_group_id"): doc["duplicate_group_id"] = existing["duplicate_group_id"]
                    if existing.get("seq"): doc["seq"] = existing["seq"]
                    update_query = {"_id": existing["_id"], "user_id": user_id}
                    db.tasks_draft.update_one(update_query, {"$set": doc})
                    draft_ids.append(str(existing["_id"]))
                    updated += 1
                else:
                    doc.update({"duplicate_group_id": uniq_key, "seq": 1, "created_at": datetime.utcnow()})
                    res = db.tasks_draft.insert_one(doc)
                    draft_ids.append(str(res.inserted_id))
                    created += 1
        except Exception as e:
            import traceback
            print(f"!!! ERRO AO IMPORTAR DRAFT: {e}")
            traceback.print_exc()
            skipped += 1

    return {"msg": f"{created} rascunhos criados, {updated} atualizados, {skipped} ignorados", "draft_ids": draft_ids}


@router.get("")
def drafts_list(emitterId: Optional[str] = None, status: Optional[str] = None, clientId: Optional[str] = None,
                current_user: UserInDB = Depends(get_current_user)):
    if not emitterId:
        return []

    user_id = ObjectId(current_user.id)
    q = {"user_id": user_id, "emitter_id": emitterId}

    if status in (None, "", "active"):
        q["status"] = {"$in": ["pending", "invalid"]}
    elif status in ("pending", "invalid", "refused", "consumed", "completed"):
        q["status"] = status
    else:
        q["status"] = status

    if clientId:
        q["client_id"] = clientId

    cur = db.tasks_draft.find(q).sort([("competencia_month", 1), ("created_at", 1)])
    return [_proj(d) for d in cur]


@router.get("/{draft_id}")
def drafts_get(draft_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(draft_id), "user_id": user_id}
    d = db.tasks_draft.find_one(query)
    if not d:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")
    return _proj(d)


@router.put("/{draft_id}")
def drafts_update(draft_id: str, payload: TaskDraftUpdate, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(draft_id), "user_id": user_id}
    d = db.tasks_draft.find_one(query)
    if not d:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")
    if d.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Apenas rascunhos 'pending' podem ser alterados")

    update = {k: v for k, v in payload.dict(exclude_none=True).items()}
    if not update:
        return {"msg": "Nada para atualizar"}

    update["updated_at"] = datetime.utcnow()
    db.tasks_draft.update_one(query, {"$set": update})
    return {"msg": "Rascunho atualizado"}


@router.delete("/{draft_id}")
def drafts_delete(draft_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(draft_id), "user_id": user_id}

    result = db.tasks_draft.delete_one(query)
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")
    return {"msg": "Rascunho removido"}


@router.post("/{draft_id}/duplicate")
def drafts_duplicate(draft_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)

    # Carrega o draft original
    original = db.tasks_draft.find_one({"_id": ObjectId(draft_id), "user_id": user_id})
    if not original:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado")

    if original.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Só é possível duplicar rascunhos pendentes")

    emitter_id = original["emitter_id"]
    client_id = original["client_id"]
    comp_month = original["competencia_month"]

    # pega todos do mesmo cliente + mês
    group = list(db.tasks_draft.find({
        "user_id": user_id,
        "emitter_id": emitter_id,
        "client_id": client_id,
        "competencia_month": comp_month,
        "status": "pending"
    }))

    # pega o maior seq existente e soma 1
    next_seq = (max([d.get("seq", 1) for d in group]) if group else 0) + 1

    new = dict(original)
    new.pop("_id")
    new["seq"] = next_seq
    new["duplicate_group_id"] = original.get("duplicate_group_id") or original["uniq_key"]
    new["uniq_key"] = f"{original['uniq_key']}:{next_seq}"
    new["created_at"] = datetime.utcnow()
    new["updated_at"] = datetime.utcnow()

    res = db.tasks_draft.insert_one(new)
    return {"msg": "Rascunho duplicado", "new_id": str(res.inserted_id)}


@router.post("/reconcile")
def drafts_reconcile(payload: Dict[str, Any] = Body(...), current_user: UserInDB = Depends(get_current_user)):
    """
    Mantém apenas as linhas marcadas (keep_indices) dentro dos grupos enviados (group_indices)
    de um preview específico, apagando o restante. Também organiza duplicate_group_id/seq.
    """
    user_id = ObjectId(current_user.id)
    emitter_id = payload.get("emitterId")
    preview_batch_id = payload.get("preview_batch_id")
    keep_indices = payload.get("keep_indices") or []
    group_indices = payload.get("group_indices") or []

    if not emitter_id or not preview_batch_id:
        raise HTTPException(status_code=400, detail="emitterId e preview_batch_id são obrigatórios")

    # garante que o emissor pertence ao usuário
    if not db.emitters.find_one({"_id": ObjectId(emitter_id), "user_id": user_id}):
        raise HTTPException(status_code=404, detail="Emissor não encontrado ou não pertence ao seu usuário")

    # 1) Apagar as linhas NÃO selecionadas dentro dos grupos informados
    delete_q = {
        "user_id": user_id,
        "emitter_id": emitter_id,
        "status": {"$in": ["pending", "invalid"]},
        "origem.preview_id": preview_batch_id,
        "origem.preview_index": {"$in": group_indices, "$nin": keep_indices},
    }
    deleted = db.tasks_draft.delete_many(delete_q).deleted_count

    # 2) Reorganizar as mantidas (atribuir duplicate_group_id / seq por cliente+mês)
    kept_q = {
        "user_id": user_id,
        "emitter_id": emitter_id,
        "status": {"$in": ["pending", "invalid"]},
        "origem.preview_id": preview_batch_id,
        "origem.preview_index": {"$in": keep_indices},
    }
    kept = list(db.tasks_draft.find(kept_q))

    # agrupa por (client_id, competencia_month)
    from collections import defaultdict
    groups = defaultdict(list)
    for d in kept:
        key = (d.get("client_id"), d.get("competencia_month"))
        groups[key].append(d)

    updated = 0
    for (client_id, comp_month), docs in groups.items():
        # existente fora do preview (ou do mesmo) para continuar numeração
        existing = list(db.tasks_draft.find({
            "user_id": user_id,
            "emitter_id": emitter_id,
            "client_id": client_id,
            "competencia_month": comp_month,
            "status": "pending",
            "_id": {"$nin": [d["_id"] for d in docs]},
        }))

        group_id = (existing[0].get("duplicate_group_id")
                    if existing and existing[0].get("duplicate_group_id")
                    else f"{emitter_id}:{client_id}:{comp_month}")
        start_seq = max([e.get("seq", 0) for e in existing], default=0)

        # ordena por índice da planilha para dar sequência previsível
        docs.sort(key=lambda x: (x.get("origem", {}).get("preview_index") or 0))
        seq = start_seq
        for d in docs:
            seq += 1
            db.tasks_draft.update_one(
                {"_id": d["_id"]},
                {"$set": {
                    "duplicate_group_id": group_id,
                    "seq": seq,
                    "status": d.get("status", "pending"),
                    "updated_at": datetime.utcnow(),
                }}
            )
            updated += 1

    return {"msg": "Reconciliação aplicada", "deleted": deleted, "updated": updated}
