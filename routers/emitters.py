from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import Optional
from bson import ObjectId
import os
from db import db
from models import EmitterUpdate, UserInDB
from utils import sanitize_document, serialize_doc, extrair_validade_certificado, encrypt_data
from routers.auth import get_current_user

UPLOAD_DIR = "uploads/certificados"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/emitters", tags=["Emitters"])


@router.post("")
def create_emitter(
    razaoSocial: str = Form(...),
    cnpj: str = Form(...),
    regimeTributacao: Optional[str] = Form(None),
    cep: Optional[str] = Form(None),
    logradouro: Optional[str] = Form(None),
    numero: Optional[str] = Form(None),
    complemento: Optional[str] = Form(None),
    bairro: Optional[str] = Form(None),
    cidade: Optional[str] = Form(None),
    uf: Optional[str] = Form(None),
    codigoIbge: Optional[str] = Form(None),
    certificado: UploadFile = File(...),
    senhaCertificado: str = Form(...),
    current_user: UserInDB = Depends(get_current_user)
):
    user_id = ObjectId(current_user.id)
    cnpj_sanitized = sanitize_document(cnpj)

    if db.emitters.find_one({"cnpj": cnpj_sanitized, "user_id": user_id}):
        raise HTTPException(status_code=400, detail="CNPJ já cadastrado para este usuário")

    data = {
        "razaoSocial": razaoSocial,
        "cnpj": cnpj_sanitized,
        "regimeTributacao": regimeTributacao,
        "cep": cep,
        "logradouro": logradouro,
        "numero": numero,
        "complemento": complemento,
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "codigoIbge": codigoIbge,
        "user_id": user_id
    }
    result = db.emitters.insert_one(data)
    emitter_id = str(result.inserted_id)

    # --- Salvar arquivo PFX ---
    filename = f"{emitter_id}_{certificado.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file_content = certificado.file.read() if hasattr(certificado, "file") else certificado.read()
    with open(filepath, "wb") as buffer:
        buffer.write(file_content)

    # --- Extrair validade diretamente com a senha pura ---
    validade = extrair_validade_certificado(filepath, senhaCertificado)

    # --- Atualizar no banco (sem criptografia da senha) ---
    db.emitters.update_one(
        {"_id": ObjectId(emitter_id)},
        {"$set": {
            "certificado_path": filepath,
            "senha_certificado": senhaCertificado,
            "validade_certificado": validade,
        }}
    )

    # --- Criar cliente "Tomador não identificado" ---
    anon_exists = db.clients.find_one({
        "nao_identificado": True,
        "emissores_ids": emitter_id,
        "user_id": user_id
    })
    if not anon_exists:
        db.clients.insert_one({
            "nome": "Tomador não identificado",
            "nao_identificado": True,
            "emissores_ids": [emitter_id],
            "created_by_system": True,
            "user_id": user_id
        })

    return {"id": emitter_id, "msg": "Emissor criado com certificado"}



@router.get("")
def list_emitters(current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    emitters = db.emitters.find({"user_id": user_id})
    return [serialize_doc(e) for e in emitters]


@router.put("/{emitter_id}")
def update_emitter(emitter_id: str, emitter: EmitterUpdate, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(emitter_id), "user_id": user_id}

    update_data = {k: v for k, v in emitter.dict().items() if v is not None}
    result = db.emitters.update_one(query, {"$set": update_data})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Emitter not found")
    return {"msg": "Emitter updated"}


@router.delete("/{emitter_id}")
def delete_emitter(emitter_id: str, current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    query = {"_id": ObjectId(emitter_id), "user_id": user_id}

    result = db.emitters.delete_one(query)

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Emitter not found")

    # Também deleta o cliente anônimo associado, dentro do mesmo cliente
    db.clients.delete_many({
        "nao_identificado": True,
        "emissores_ids": emitter_id,
        "user_id": user_id
    })
    return {"msg": "Emitter deleted"}
