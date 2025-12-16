from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
import tempfile
from fastapi import Path
from fastapi.middleware.cors import CORSMiddleware
from backend.transmitter import enviar_nfse_pkcs12
from apscheduler.schedulers.background import BackgroundScheduler
from bson import ObjectId
from db import db
import pandas as pd
import traceback
import os
from datetime import datetime
from backend.signer import assinar_xml
from backend.transmitter import baixar_danfse_pdf
from utils import (
    serialize_doc,
    extrair_validade_certificado,
    gerar_dpsXmlGZipB64,
    parse_nfse_response,
    substituir_dps_no_xml,
    is_dps_repetida,
    next_dps,
    sanitize_document,
    remover_assinatura
)
from routers import emitters, clients, notas, drafts, tasks, auth
from routers.clients import atualizar_dados_clientes
from routers.aliquota import router as aliquota_router, tarefa_recalcular_aliquotas_mensais
from dotenv import load_dotenv


load_dotenv()

UPLOAD_DIR = "uploads/certificados"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app = FastAPI(title="NFSe Nacional")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite
        "http://localhost:3000",  # CRA
        "http://10.0.0.172:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(emitters.router)
app.include_router(clients.router)
app.include_router(notas.router)
app.include_router(drafts.router)
app.include_router(tasks.router)
app.include_router(aliquota_router)


# ---------------- CERTIFICADO ----------------
@app.post("/emitters/{emitter_id}/certificate")
async def upload_certificate(emitter_id: str, file: UploadFile = File(...), senha: str = Form(...)):
    emitter = db.emitters.find_one({"_id": ObjectId(emitter_id)})
    if not emitter:
        raise HTTPException(status_code=404, detail="Emitter not found")

    filename = f"{emitter_id}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as buffer:
        buffer.write(await file.read())

    # 🔹 extrai validade real do certificado
    validade = extrair_validade_certificado(filepath, senha)

    db.emitters.update_one(
        {"_id": ObjectId(emitter_id)},
        {
            "$set": {
                "certificado_path": filepath,
                "senha_certificado": senha,
                "validade_certificado": validade,
            }
        },
    )
    return {"msg": "Certificado atualizado com sucesso", "validade": validade}


# --- VÍNCULO CLIENTE <-> EMISSOR ---
@app.get("/emitters/{emitter_id}/clients")
def list_clients_by_emitter(emitter_id: str):
    """Lista clientes vinculados a um emissor (via campo emissores_ids)."""
    cur = db.clients.find({"emissores_ids": emitter_id})
    return [serialize_doc(c) for c in cur]


@app.post("/emitters/{emitter_id}/clients/{client_id}")
def attach_client_to_emitter(emitter_id: str = Path(...), client_id: str = Path(...)):
    """Vincula um cliente a um emissor (idempotente)."""
    # garante que ambos existem
    if not db.emitters.find_one({"_id": ObjectId(emitter_id)}):
        raise HTTPException(status_code=404, detail="Emissor não encontrado")
    if not db.clients.find_one({"_id": ObjectId(client_id)}):
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    db.clients.update_one(
        {"_id": ObjectId(client_id)},
        {"$addToSet": {"emissores_ids": emitter_id}}
    )
    return {"msg": "Cliente vinculado ao emissor"}


@app.delete("/emitters/{emitter_id}/clients/{client_id}")
def detach_client_from_emitter(emitter_id: str = Path(...), client_id: str = Path(...)):
    """Remove o vínculo do cliente com o emissor."""
    if not db.clients.find_one({"_id": ObjectId(client_id)}):
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    db.clients.update_one(
        {"_id": ObjectId(client_id)},
        {"$pull": {"emissores_ids": emitter_id}}
    )
    return {"msg": "Cliente desvinculado do emissor"}


# ---------------- TEMPLATES PLANILHA ----------------
@app.get("/templates/clientes")
def download_template_clientes():
    """Gera e baixa a planilha modelo de clientes"""

    colunas = [
        "documento (CNPJ/CPF)",
        "nome (obrigatório se CPF)",
        "cep (obrigatório se CPF)",
        "numero (obrigatório)",
        "emissores_cnpjs (separar múltiplos por vírgula)"
    ]
    df = pd.DataFrame({c: pd.Series(dtype="string") for c in colunas})

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")

    # use o engine xlsxwriter para aplicar formato de texto na coluna
    with pd.ExcelWriter(tmp.name, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="clientes")
        wb = writer.book
        ws = writer.sheets["clientes"]

        text_fmt = wb.add_format({'num_format': '@'})
        ws.set_column('A:F', 25, text_fmt)

    return FileResponse(
        tmp.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="modelo_clientes.xlsx"
    )


@app.get("/templates/notas")
def download_template_notas():
    """
    Gera a planilha modelo com instruções no cabeçalho (linha 1).
    Agora padronizada como clientes: usa xlsxwriter, tudo texto exceto Valor.
    """
    header_display = [
        "CPF/CNPJ (somente números)",
        "Valor (0.000,00)",
        "Descrição do serviço",
        "Data de emissão (DD/MM/AAAA)",
        "CTN (cód. do serviço)",
        "País da prestação (BRASIL/EXTERIOR)",
        "ISS retido (S/N)",
    ]

    # cria DataFrame vazio com colunas
    df = pd.DataFrame({c: pd.Series(dtype="string") for c in header_display})

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")

    with pd.ExcelWriter(tmp.name, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="notas")
        wb = writer.book
        ws = writer.sheets["notas"]

        # Formatos
        text_fmt = wb.add_format({"num_format": "@"})  # texto
        money_fmt = wb.add_format({"num_format": "#,##0.00"})  # valor monetário
        date_fmt = wb.add_format({'num_format': 'dd/mm/yyyy'})
        header_fmt = wb.add_format({
            "bold": True,
            "bg_color": "#E3F2EF",
            "align": "center",
            "valign": "vcenter",
        })

        # aplicar formatação nas colunas
        ws.set_row(0, None, header_fmt)  # cabeçalho
        ws.set_column("A:A", 22, text_fmt)   # CPF/CNPJ
        ws.set_column("B:B", 14, money_fmt)  # Valor
        ws.set_column("C:C", 42, text_fmt)   # Descrição
        ws.set_column("D:D", 22, text_fmt)   # Data emissão
        ws.set_column("E:E", 18, text_fmt)   # CTN
        ws.set_column("F:F", 22, text_fmt)   # País
        ws.set_column("G:G", 16, text_fmt)   # ISS Retido

        # congelar linha 1
        ws.freeze_panes(1, 0)

        # validações data
        ws.data_validation("D2:D10000", {
            'validate': 'custom',
            'value': '=AND(LEN(D2)=10, ISNUMBER(DATEVALUE(D2)))',
            'input_title': 'Data de Emissão',
            'input_message': 'Por favor, use o formato DD/MM/AAAA.',
            'error_title': 'Data Inválida',
            'error_message': 'O formato deve ser DD/MM/AAAA (ex: 04/11/2025).'
        })

        # validações ISS e País
        ws.data_validation("I2:I10000", {
            "validate": "list",
            "source": ["S", "N"],
            "input_message": "Preencha com S ou N",
        })
        ws.data_validation("H2:H10000", {
            "validate": "list",
            "source": ["BRASIL", "EXTERIOR"],
            "input_message": "Use BRASIL ou EXTERIOR",
        })

    return FileResponse(
        tmp.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="modelo_notas.xlsx",
    )


# ======================================================
# 🔹 Função que transmite tasks pendentes automaticamente
# ======================================================
def process_pending_nfse():
    """Busca tasks pendentes e transmite automaticamente via prefeitura."""
    try:
        pendentes = list(db.tasks.find({"status": "pending"}).limit(5))
        if not pendentes:
            return

        print(f"🔍 Encontradas {len(pendentes)} tasks pendentes")

        for t in pendentes:
            try:
                task_id = str(t["_id"])
                emitter_id = t.get("emitter_id")
                if not emitter_id:
                    print(f"Task {task_id} sem emitter_id, ignorando.")
                    continue

                # 🔹 Busca emissor e certificado
                emitter = db.emitters.find_one({"_id": ObjectId(emitter_id), "user_id": t["user_id"]})
                if not emitter:
                    print(f"Emissor da task {task_id} não encontrado.")
                    continue

                if not emitter.get("certificado_path"):
                    print(f"Emissor {emitter_id} sem certificado.")
                    continue

                xml_assinado = (t.get("response") or {}).get("xml")
                if not xml_assinado:
                    print(f"Task {task_id} sem XML assinado, ignorando.")
                    continue

                # 🔹 Compacta XML e codifica em Base64 (como prefeitura exige)
                dps_b64 = gerar_dpsXmlGZipB64(xml_assinado)
                pfx_pwd = emitter.get("senha_certificado") or ""

                print(f"Enviando task {task_id} para prefeitura...")
                resp = enviar_nfse_pkcs12(dps_b64, emitter["certificado_path"], pfx_pwd)

                raw_resp = resp.get("body", "")
                status_code = resp.get("status", 0)
                xml_nfse = resp.get("xml_nfse")
                pdf_base64 = resp.get("pdf_base64")
                id_dps = resp.get("id_dps")
                chave_acesso = resp.get("chave_acesso")

                receipt = parse_nfse_response(xml_nfse) if xml_nfse else parse_nfse_response(raw_resp)

                if not receipt.get("numero_nfse") and chave_acesso:
                    receipt["numero_nfse"] = str(chave_acesso)

                if status_code in (200, 201) and (xml_nfse or chave_acesso) and not receipt.get("erros"):
                    receipt["success"] = True

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

                db.tasks.update_one({"_id": ObjectId(task_id)}, {"$set": update_set})
                print(f"Task {task_id} atualizada para '{new_status}'")

            except Exception as e:
                print(f"Erro ao processar task {t.get('_id')}: {e}")
                traceback.print_exc()
                db.tasks.update_one(
                    {"_id": t["_id"]},
                    {"$set": {
                        "status": "error",
                        "error_at": datetime.utcnow(),
                        "transmit": {"error": str(e)}
                    }}
                )

    except Exception as e:
        print("Erro geral no scheduler:", e)
        traceback.print_exc()


def process_retry_dps():
    retry_tasks = list(db.tasks.find({"status": "retry_dps"}).limit(5))
    if not retry_tasks:
        return

    print(f"?? Encontradas {len(retry_tasks)} tasks retry_dps para recálculo de DPS")

    for t in retry_tasks:
        try:
            emitter = db.emitters.find_one({"_id": ObjectId(t["emitter_id"]), "user_id": t["user_id"]})
            if not emitter:
                print("Emissor não encontrado")
                continue

            response = t.get("response") or {}

            # tenta pegar XML do response novo
            xml_original = response.get("xml")

            # se não tiver (caso antigo), tenta pegar do campo legado 'response.xml'
            if not xml_original:
                xml_original = t.get("response.xml")

            if not xml_original:
                print(f"Task {t['_id']} sem XML original, ignorando retry.")
                continue

            # 1) GERAR NOVO DPS
            nova_serie = "00002"
            dps = next_dps(db, t["emitter_id"], serie=nova_serie)

            # 2) VARIÁVEIS QUE TAMBÉM FALTAVAM
            emitter_cnpj = sanitize_document(emitter["cnpj"])
            municipio = str(emitter.get("codigoIbge") or emitter.get("codigo_ibge") or "").zfill(7)

            # 3) remover assinatura antiga
            xml_sem_ass = remover_assinatura(xml_original)

            # 4) substituir DPS no XML com ID novo, série nova, nº novo
            xml_novo = substituir_dps_no_xml(
                xml_sem_ass,
                nova_serie=dps["serie"],
                novo_numero=dps["numero"],
                emitter_cnpj=emitter_cnpj,
                municipio_ibge=municipio
            )

            # 5) gerar assinatura nova
            xml_assinado = assinar_xml(
                xml_novo,
                pfx_path=emitter["certificado_path"],
                pfx_password=emitter["senha_certificado"]
            )

            # 6) salvar alterações
            # Mescla o response existente com o novo XML corrigido
            response_atual = t.get("response", {})

            response_atual["xml"] = xml_assinado
            response_atual["updated_at"] = datetime.utcnow()

            db.tasks.update_one(
                {"_id": t["_id"]},
                {"$set": {
                    "status": "pending",
                    "response": response_atual,
                    "dps": {
                        "serie": dps["serie"],
                        "numero": dps["numero"],
                        "status": "ajustado"
                    },
                    "updated_at": datetime.utcnow()
                }}
            )

            print(f"? Task {t['_id']} corrigida e voltou para pending")

        except Exception as e:
            print("Erro processando retry_dps:", e)
            traceback.print_exc()


def tarefa_recuperar_pdfs_pendentes():
    """
    Busca notas que foram ACEITAS (Status 'accepted') mas que estão SEM PDF.
    Filtro abrangente: Null, Vazio ou Inexistente.
    """
    print(f"[SCHEDULER PDF] Iniciando varredura de PDFs pendentes: {datetime.now()}")

    # Filtro mais robusto: aceita nulo ou string vazia
    filtro = {
        "status": "accepted",
        "$or": [
            {"transmit.pdf_base64": None},
            {"transmit.pdf_base64": ""},
            {"transmit.pdf_base64": {"$exists": False}}
        ],
        "transmit.chave_acesso": {"$ne": None}
    }

    # Debug: Mostra quantos encontrou antes de processar
    total_pendentes = db.tasks.count_documents(filtro)
    print(f"[SCHEDULER PDF] Notas encontradas no banco para processar: {total_pendentes}")

    if total_pendentes == 0:
        return

    pendentes = list(db.tasks.find(filtro).limit(20))
    count = 0

    for task in pendentes:
        try:
            chave = task.get("transmit", {}).get("chave_acesso")
            emitter_id = task.get("emitter_id")
            task_id = str(task["_id"])

            if not chave:
                print(f"  -> Pular task {task_id}: Sem chave de acesso.")
                continue

            # Busca dados do emissor para o certificado
            emitter = db.emitters.find_one({"_id": ObjectId(emitter_id)})
            if not emitter:
                print(f"  -> Pular task {task_id}: Emissor não encontrado.")
                continue

            # Caminho do certificado
            pfx_path = emitter.get("certificado_path")
            senha_cert = emitter.get("senha_certificado")

            if not pfx_path or not os.path.exists(pfx_path):
                # Tenta corrigir caminho relativo se necessário
                pfx_path_fallback = os.path.join("uploads", "certificados", os.path.basename(pfx_path or "ignorar"))
                if os.path.exists(pfx_path_fallback):
                    pfx_path = pfx_path_fallback
                else:
                    print(f"  -> ERRO: Certificado não encontrado no disco para emissor {emitter.get('razaoSocial')}: {pfx_path}")
                    continue

            print(f"  -> Baixando PDF Task {task_id} (Chave: {chave})...")

            # Tenta baixar
            pdf_b64 = baixar_danfse_pdf(chave, pfx_path, senha_cert)

            if pdf_b64:
                # Salva no banco
                db.tasks.update_one(
                    {"_id": task["_id"]},
                    {"$set": {"transmit.pdf_base64": pdf_b64}}
                )
                print(f"  -> SUCESSO! PDF salvo.")
                count += 1
            else:
                print(f"  -> Falha: Portal retornou 404/Erro ainda.")

        except Exception as e:
            print(f"  -> Erro ao processar task {task.get('_id')}: {e}")

    print(f"[SCHEDULER PDF] Finalizado. {count} PDFs recuperados nesta rodada.")


# ======================================================
# 🔹 Inicializa o scheduler no startup
# ======================================================
def start_scheduler():
    scheduler = BackgroundScheduler()
    # roda a cada 60 segundos
    scheduler.add_job(process_pending_nfse, "interval", seconds=15)
    scheduler.add_job(process_retry_dps, "interval", seconds=20)
    scheduler.add_job(tarefa_recuperar_pdfs_pendentes, "interval", minutes=30)
    scheduler.add_job(
        atualizar_dados_clientes,
        "cron",
        hour=1,
        minute=0,
        id="atualizacao_cadastral_diaria"
    )
    scheduler.add_job(
        tarefa_recalcular_aliquotas_mensais,
        "cron",
        day=1,
        hour=8,
        minute=0,
        id="recalculo_aliquota_mensal",
        replace_existing=True
    )
    scheduler.start()
    print("🕒 Scheduler de transmissão iniciado (checa pendentes a cada 15s)")


@app.on_event("startup")
def startup_event():
    start_scheduler()


# ======================================================
# 🔹 Rota simples de saúde
# ======================================================
@app.get("/")
def root():
    return {"msg": "API NFSe rodando com scheduler automático"}


# run back -> uvicorn main:app --host 0.0.0.0 --port 6600
# run  front -> cd frontend  npm run dev -- --host 0.0.0.0
