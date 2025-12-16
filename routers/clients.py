from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Depends, Query
from bson import ObjectId
import pandas as pd
import requests
from db import db
from models import ClientCreate, ClientUpdate, UserInDB
from routers.auth import get_current_user
from utils import sanitize_document, serialize_doc, identificar_documento
import time
from datetime import datetime, timedelta
import tempfile
import os

router = APIRouter(prefix="/clients", tags=["Clients"])

RECEITAWS_URL = "https://www.receitaws.com.br/v1/cnpj/{}"
# AJUSTE: 21 segundos garante < 3 req/min com margem de segurança
THROTTLE_SECONDS = 21
DAYS_BETWEEN_UPDATES = 30


def _fill_if_empty(target: dict, key: str, value):
    if value is None:
        return
    cur = target.get(key)
    if cur is None or (isinstance(cur, str) and cur.strip() == ""):
        target[key] = value


def _enrich_from_receitaws(cnpj: str) -> dict:
    """
    Consulta a ReceitaWS. Retorna um dict com os dados ou None em caso de erro/rate-limit.
    """
    url = RECEITAWS_URL.format(cnpj)
    print(f"?? Consultando ReceitaWS: {url}")

    try:
        resp = requests.get(url, timeout=15)

        # AJUSTE: Tratamento explícito do 429 (Rate Limit)
        if resp.status_code == 429:
            print(f"?? [AVISO] Rate Limit atingido para {cnpj}. Pulando...")
            return None

        if resp.status_code != 200:
            print(f"?? [ERRO] Status {resp.status_code} para {cnpj}")
            return None

        try:
            data = resp.json()
        except Exception:
            print("?? [ERRO] Falha ao converter JSON da ReceitaWS")
            return None

        # AJUSTE: Se a API retornar ERROR, não retornamos dict vazio, retornamos None
        if isinstance(data, dict) and data.get("status") == "ERROR":
            msg = data.get("message") or "ReceitaWS retornou ERROR"
            print(f"?? [API ERROR] {msg}")
            return None

        # Sucesso
        print(f"?? Resposta ReceitaWS OK para {cnpj}")
        return {
            "nome": data.get("nome"), "email": data.get("email"),
            "cep": (data.get("cep") or "").replace("-", "").strip() if data.get("cep") else None,
            "logradouro": data.get("logradouro"), "bairro": data.get("bairro"),
            "cidade": data.get("municipio"), "estado": data.get("uf"),
        }

    except Exception as e:
        print(f"?? [EXCEPTION] Erro ao consultar ReceitaWS: {e}")
        return None


# ---------------- CRUD SEGURO ---------------- #

@router.post("")
def create_client(client: ClientCreate, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    data = client.dict(exclude_none=True)
    data["user_id"] = user_id

    if data.get("nao_identificado"):
        raise HTTPException(status_code=400, detail="Campo nao_identificado é reservado ao sistema")

    if "documento" in data:
        tipo, numero = identificar_documento(data["documento"])
        data[tipo] = numero
        data.pop("documento", None)

    if "cnpj" in data:
        data["cnpj"] = sanitize_document(data["cnpj"])
    if "cpf" in data:
        data["cpf"] = sanitize_document(data["cpf"])

    filtro = {"user_id": user_id, "$or": []}
    if data.get("cpf"):
        filtro["$or"].append({"cpf": data["cpf"]})
    if data.get("cnpj"):
        filtro["$or"].append({"cnpj": data["cnpj"]})

    existing = db.clients.find_one(filtro)

    if existing:
        if not existing.get("ativo", True):
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "inativo",
                    "client_id": str(existing["_id"]),
                    "message": f"Cliente '{existing.get('nome', 'Sem nome')}' já existe, mas está inativo."
                }
            )
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "duplicado",
                    "message": f"Cliente já cadastrado: {existing.get('nome', 'Sem nome')} ({existing.get('cnpj') or existing.get('cpf') or 'sem documento'})"
                }
            )

    if data.get("cpf") and not data.get("nome"):
        raise HTTPException(status_code=400, detail="Nome é obrigatório para CPF")
    if data.get("cpf") and not data.get("cep"):
        raise HTTPException(status_code=400, detail="CEP é obrigatório para CPF")
    if not data.get("numero"):
        raise HTTPException(status_code=400, detail="Número do logradouro é obrigatório")

    if data.get("cnpj"):
        try:
            data_api = _enrich_from_receitaws(data["cnpj"])
            # AJUSTE: Só preenche se retornou dados válidos
            if data_api:
                for key, value in data_api.items():
                    _fill_if_empty(data, key, value)
        except Exception as e:
            print(f"Falha ReceitaWS no create: {e}")

    cep = sanitize_document(data.get("cep", "") or "")
    if cep and len(cep) == 8:
        try:
            resp = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
            if "erro" not in resp:
                data.update({
                    "logradouro": data.get("logradouro") or resp.get("logradouro"),
                    "bairro": data.get("bairro") or resp.get("bairro"),
                    "cidade": data.get("cidade") or resp.get("localidade"),
                    "estado": data.get("estado") or resp.get("uf"),
                    "codigoIbge": data.get("codigoIbge") or str(resp.get("ibge") or "").strip(),
                })
        except Exception:
            pass

    data["ativo"] = True
    data["created_at"] = datetime.utcnow()
    data["updated_at"] = datetime.utcnow()

    result = db.clients.insert_one(data)
    new_client = db.clients.find_one({"_id": result.inserted_id})
    return serialize_doc(new_client)


@router.put("/{client_id}")
def update_client(client_id: str, client: ClientUpdate, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(client_id), "user_id": user_id}

    current_doc = db.clients.find_one(query)
    if not current_doc:
        raise HTTPException(status_code=404, detail="Client not found")
    if current_doc.get("nao_identificado"):
        raise HTTPException(status_code=400, detail="Este cliente é do sistema e não pode ser alterado")

    data = client.dict(exclude_none=True, exclude_unset=True)
    data = {k: v for k, v in data.items() if not (isinstance(v, str) and v.strip() == "")}
    if "nao_identificado" in data:
        data.pop("nao_identificado", None)

    if "cnpj" in data:
        data["cnpj"] = sanitize_document(data["cnpj"])
    if "cpf" in data:
        data["cpf"] = sanitize_document(data["cpf"])
    if "documento" in data:
        tipo, numero = identificar_documento(data["documento"])
        data[tipo] = numero
        data.pop("documento", None)

    if data.get("cpf") and not data.get("nome"):
        raise HTTPException(status_code=400, detail="Nome é obrigatório para CPF")
    if data.get("cpf") and not data.get("cep"):
        raise HTTPException(status_code=400, detail="CEP é obrigatório para CPF")
    if not data.get("numero"):
        raise HTTPException(status_code=400, detail="Número do logradouro é obrigatório")

    cep = sanitize_document(data.get("cep", "") or "")
    if cep and len(cep) == 8:
        try:
            resp = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
            if "erro" not in resp:
                data.update({
                    "logradouro": resp.get("logradouro"),
                    "bairro": resp.get("bairro"),
                    "cidade": resp.get("localidade"),
                    "estado": resp.get("uf"),
                    "codigoIbge": resp.get("ibge"),
                })
        except Exception:
            pass

    result = db.clients.update_one(query, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"msg": "Client updated"}


@router.delete("/{client_id}")
def delete_client(client_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(client_id), "user_id": user_id}

    d = db.clients.find_one(query)
    if not d:
        raise HTTPException(status_code=404, detail="Client not found")
    if d.get("nao_identificado"):
        raise HTTPException(status_code=400, detail="Este cliente é do sistema e não pode ser excluído")

    db.clients.update_one(query, {"$set": {"ativo": False, "data_distrato": datetime.utcnow()}})
    return {"msg": "Cliente desativado (distrato registrado)"}


@router.get("")
def list_clients(incluir_inativos: bool = Query(False), current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"user_id": user_id, "nao_identificado": {"$ne": True}}

    if not incluir_inativos:
        query["ativo"] = {"$ne": False}

    cur = db.clients.find(query).sort("nome", 1)
    return [serialize_doc(c) for c in cur]


@router.put("/{client_id}/reativar")
def reativar_client(client_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(client_id), "user_id": user_id}
    result = db.clients.update_one(
        query, {"$set": {"ativo": True, "updated_at": datetime.utcnow()}, "$unset": {"data_distrato": ""}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return {"msg": "Cliente reativado com sucesso"}


# ---------------- IMPORTAÇÃO SEGURA ---------------- #

@router.post("/import")
async def import_clients(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        current_user: UserInDB = Depends(get_current_user)
):
    if not file.filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=400, detail="Arquivo inválido")

    temp_dir = tempfile.gettempdir()
    path = os.path.join(temp_dir, file.filename)
    with open(path, "wb") as f:
        f.write(await file.read())

    job_id_obj = ObjectId()
    db.imports.insert_one({
        "_id": job_id_obj,
        "user_id": ObjectId(current_user.id),
        "status": "pending", "inserted": 0, "skipped": 0, "errors": [],
        "started_at": datetime.utcnow(), "finished_at": None,
        "file_name": file.filename,
    })

    background_tasks.add_task(process_import_file, str(job_id_obj), path, current_user.id)
    return {"msg": "Importação iniciada", "job_id": str(job_id_obj)}


def process_import_file(job_id_str: str, path: str, user_id_str: str):
    job_id = ObjectId(job_id_str)
    user_id = ObjectId(user_id_str)

    try:
        if path.lower().endswith(".xlsx"):
            df = pd.read_excel(path, engine="openpyxl", dtype=str, keep_default_na=False)
        else:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)

        df.columns = [c.strip() for c in df.columns]
        colunas_oficiais = [
            "documento (CNPJ/CPF)", "nome (obrigatório se CPF)",
            "cep (obrigatório se CPF)", "numero (obrigatório)",
            "emissores_cnpjs (separar múltiplos por vírgula)",
        ]
        if set(df.columns) != set(colunas_oficiais):
            raise ValueError(f"Planilha inválida. Esperado: {colunas_oficiais}, recebido: {list(df.columns)}")

        df = df.fillna("")
        inserted, skipped, erros = 0, 0, []

        emissores = list(db.emitters.find({}, {"_id": 1, "cnpj": 1}))

        for idx, row in df.iterrows():
            try:
                doc_raw = (row.get("documento (CNPJ/CPF)") or "").strip()
                nome_raw = (row.get("nome (obrigatório se CPF)") or "").strip()
                cep_raw = (row.get("cep (obrigatório se CPF)") or "").strip()
                numero_raw = (row.get("numero (obrigatório)") or "").strip()
                emissores_raw = (row.get("emissores_cnpjs (separar múltiplos por vírgula)") or "").strip()

                doc = sanitize_document(doc_raw)
                cep = sanitize_document(cep_raw)

                if 1 <= len(doc) <= 11:
                    doc = doc.zfill(11)
                elif 12 <= len(doc) <= 14:
                    doc = doc.zfill(14)
                elif doc:
                    raise ValueError(f"Documento com {len(doc)} dígitos inválido: {doc_raw}")

                if 0 < len(cep) < 8:
                    cep = cep.zfill(8)

                payload = {
                    "user_id": user_id,
                    "nome": nome_raw,
                    "documento": doc,
                    "email": None,
                    "cep": cep,
                    "numero": numero_raw or None,
                }

                if payload.get("documento"):
                    tipo, numero = identificar_documento(payload["documento"])
                    payload[tipo] = numero

                filtro_dup = {"user_id": user_id}
                if payload.get("cpf"):
                    filtro_dup["cpf"] = payload.get("cpf")
                if payload.get("cnpj"):
                    filtro_dup["cnpj"] = payload.get("cnpj")

                if len(filtro_dup) > 1 and db.clients.find_one(filtro_dup):
                    raise ValueError("Cliente com este documento já existe para este usuário")

                emissores_ids = []
                if emissores_raw:
                    for cnpj_text in [x.strip() for x in emissores_raw.split(",") if x.strip()]:
                        cnpj_limpo = sanitize_document(cnpj_text)
                        match = next((e["_id"] for e in emissores if sanitize_document(e["cnpj"]) == cnpj_limpo), None)
                        if match:
                            emissores_ids.append(str(match))
                if emissores_ids:
                    payload["emissores_ids"] = emissores_ids

                # Enriquecimento automático
                if payload.get("cnpj"):
                    time.sleep(THROTTLE_SECONDS)
                    data_api = _enrich_from_receitaws(payload["cnpj"])
                    # AJUSTE: Só preenche se data_api não for None
                    if data_api:
                        for key, value in data_api.items():
                            _fill_if_empty(payload, key, value)

                # ViaCEP
                cep_clean = sanitize_document(payload.get("cep") or "")
                if cep_clean and len(cep_clean) == 8:
                    try:
                        resp = requests.get(f"https://viacep.com.br/ws/{cep_clean}/json/", timeout=10).json()
                        if "erro" not in resp:
                            ibge_code = str(resp.get("ibge") or "").strip()
                            if not ibge_code and resp.get("localidade") and resp.get("uf"):
                                try:
                                    lookup = requests.get(
                                        f"https://servicodados.ibge.gov.br/api/v1/localidades/municipios?nome={resp['localidade']}",
                                        timeout=10
                                    ).json()
                                    match = next((m for m in lookup if
                                                  m["microrregiao"]["mesorregiao"]["UF"]["sigla"] == resp["uf"]), None)
                                    if match:
                                        ibge_code = str(match["id"])
                                except Exception:
                                    pass

                            payload.update({
                                "logradouro": payload.get("logradouro") or resp.get("logradouro"),
                                "bairro": payload.get("bairro") or resp.get("bairro"),
                                "cidade": payload.get("cidade") or resp.get("localidade"),
                                "estado": payload.get("estado") or resp.get("uf"),
                                "codigoIbge": payload.get("codigoIbge") or ibge_code,
                            })

                    except Exception as e:
                        print(f"Erro ao consultar ViaCEP {cep_clean}: {e}")

                if not payload.get("documento"):
                    raise ValueError("Documento obrigatório não informado")
                if payload.get("cpf") and not payload.get("nome"):
                    raise ValueError("Nome obrigatório para CPF")
                if payload.get("cpf") and not payload.get("cep"):
                    raise ValueError("CEP obrigatório para CPF")
                if not payload.get("numero"):
                    raise ValueError("Número do logradouro é obrigatório")
                if not payload.get("nome"):
                    raise ValueError("Nome não informado e API externa não conseguiu preencher")

                payload["ativo"] = True
                payload["created_at"] = datetime.utcnow()
                payload["updated_at"] = datetime.utcnow()

                db.clients.insert_one(payload)
                inserted += 1

            except Exception as e:
                skipped += 1
                erros.append({
                    "linha": int(idx) + 2,
                    "documento": row.get("documento (CNPJ/CPF)") or "",
                    "erro": str(e)
                })

            db.imports.update_one(
                {"_id": job_id},
                {"$set": {
                    "inserted": inserted,
                    "skipped": skipped,
                    "errors": erros,
                    "status": "running"
                }}
            )

        db.imports.update_one({"_id": job_id}, {"$set": {"status": "finished", "finished_at": datetime.utcnow()}})

    except Exception as e:
        db.imports.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "error",
                "errors": [{"linha": 1, "erro": str(e)}],
                "finished_at": datetime.utcnow()
            }}
        )


@router.get("/import/status/{job_id}")
def get_import_status(job_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(job_id), "user_id": user_id}
    job = db.imports.find_one(query)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return serialize_doc(job)


@router.get("/enrich/{documento}")
def enrich_client(documento: str, current_user: UserInDB = Depends(get_current_user)):
    doc = sanitize_document(documento)
    if len(doc) == 14:
        try:
            data_api = _enrich_from_receitaws(doc)
            if data_api:
                return {"status": "ok", "data": data_api}
            else:
                return {"status": "error", "data": {}, "message": "API indisponível ou Rate Limit"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Falha na consulta: {e}")
    return {"status": "ignored", "data": {}}


# ---------------- ROTINA DE ATUALIZAÇÃO SEGURA ---------------- #

def atualizar_dados_clientes():
    inicio = datetime.utcnow()
    limite_data = datetime.utcnow() - timedelta(days=DAYS_BETWEEN_UPDATES)

    # Busca apenas clientes ativos, com CNPJ e que não foram atualizados recentemente
    query = {
        "ativo": True,
        "cnpj": {"$exists": True, "$ne": None},
        "updated_at": {"$lte": limite_data}
    }

    clientes = list(db.clients.find(query))
    total = len(clientes)

    print(f"Clientes a verificar: {total}")

    count_atualizados = 0
    count_sem_alteracao = 0
    count_ignorados = 0

    for i, cli in enumerate(clientes, start=1):
        cnpj = cli.get("cnpj")

        # AJUSTE: Consulta a API com proteção
        data_api = _enrich_from_receitaws(cnpj)

        # AJUSTE: Se retornou None (429 ou erro), PULA e não mexe no banco
        if not data_api:
            print(f"[{i}/{total}] CNPJ {cnpj} ignorado (Erro/Limit API).")
            count_ignorados += 1
            # Dorme mesmo no erro para não insistir no bloqueio
            time.sleep(THROTTLE_SECONDS)
            continue

        try:
            update_fields = {}
            campos_atualizados = []

            for key, value in data_api.items():
                if value in (None, "", " "):
                    continue

                valor_atual = cli.get(key)

                val_api = str(value).strip() if isinstance(value, str) else value
                val_db = str(valor_atual).strip() if isinstance(valor_atual, str) else valor_atual

                if val_api != val_db:
                    update_fields[key] = val_api
                    campos_atualizados.append(key)

            if update_fields:
                update_fields["updated_at"] = datetime.utcnow()
                update_fields["atualizado_recente"] = True
                update_fields["campos_atualizados"] = campos_atualizados

                db.clients.update_one(
                    {"_id": cli["_id"]},
                    {"$set": update_fields}
                )
                count_atualizados += 1
                print(f"[{i}/{total}] Atualizado: {cli.get('nome', '-')} | Mudanças: {campos_atualizados}")

            else:
                # AJUSTE: Se não mudou, atualiza a data para não verificar amanhã de novo
                db.clients.update_one(
                    {"_id": cli["_id"]},
                    {"$set": {"updated_at": datetime.utcnow(), "atualizado_recente": False}}
                )
                count_sem_alteracao += 1
                print(f"[{i}/{total}] Sem alterações: {cnpj}")

        except Exception as e:
            print(f"Erro ao processar atualização CNPJ {cnpj}: {e}")
            count_ignorados += 1

        # AJUSTE: Pausa APÓS CADA requisição (sem lotes)
        if i < total:
            time.sleep(THROTTLE_SECONDS)

    fim = datetime.utcnow()
    duracao_min = (fim - inicio).total_seconds() / 60

    print("------------ RESUMO ------------")
    print(f"Duração: {duracao_min:.2f} min")
    print(f"Atualizados: {count_atualizados}")
    print(f"Sem alteração: {count_sem_alteracao}")
    print(f"Ignorados (Erro API): {count_ignorados}")
    print("--------------------------------")


@router.get("/stats")
def get_client_stats(current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)

    total = db.clients.count_documents({"user_id": user_id, "nao_identificado": {"$ne": True}})
    ativos = db.clients.count_documents({"user_id": user_id, "ativo": True, "nao_identificado": {"$ne": True}})
    inativos = total - ativos
    atualizados = db.clients.count_documents({"user_id": user_id, "atualizado_recente": True})

    return {
        "total": total,
        "ativos": ativos,
        "inativos": inativos,
        "atualizados": atualizados,
    }


@router.get("/recent-updates")
def get_recent_updates(current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    cur = db.clients.find(
        {"user_id": user_id, "ativo": True, "atualizado_recente": True},
        {"nome": 1, "cnpj": 1, "cpf": 1, "campos_atualizados": 1}
    ).sort("updated_at", -1)
    return [serialize_doc(c) for c in cur]


@router.post("/clear-recent-updates")
def clear_recent_updates(current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    db.clients.update_many(
        {"user_id": user_id, "atualizado_recente": True},
        {"$set": {"atualizado_recente": False}}
    )
    return {"msg": "Status de atualização recente limpo."}
