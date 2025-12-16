from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from bson import ObjectId
from datetime import datetime, timedelta
from fastapi.responses import JSONResponse
from db import db
from routers.auth import get_current_user
from models import UserInDB
import re
import pdfplumber

router = APIRouter(prefix="/aliquota", tags=["Aliquota"])

# ----------------- Tabela Anexo III -----------------
TABELA_ANEXO_III = [
    (0, 180000.00, 0.06, 0.00),
    (180000.01, 360000.00, 0.112, 9360.00),
    (360000.01, 720000.00, 0.135, 17640.00),
    (720000.01, 1800000.00, 0.16, 35640.00),
    (1800000.01, 3600000.00, 0.21, 125640.00),
    (3600000.01, 4800000.00, 0.33, 648000.00),
]


# ----------------- AUXILIARES -----------------
def parse_num(valor_str: str) -> float:
    if not valor_str: return 0.0
    limpo = re.sub(r"[^0-9,.]", "", valor_str)
    if ',' in limpo and '.' in limpo:
        limpo = limpo.replace('.', '').replace(',', '.')
    elif ',' in limpo:
        limpo = limpo.replace(',', '.')
    try:
        return float(limpo)
    except:
        return 0.0


def separar_texto_colado(texto: str) -> str:
    return re.sub(r"(,\d{2})(\d{2}/\d{4})", r"\1 \2", texto)


def get_receita_data(mes, ano, receitas_dict):
    """Busca no dicionário de receitas (usado no PDF)"""
    chave = f"{mes:02d}/{ano}"
    return receitas_dict.get(chave, 0.0)


def extrair_dados_pgdas(pdf_file):
    pdf_file.file.seek(0)
    try:
        with pdfplumber.open(pdf_file.file) as pdf:
            if not pdf.pages: raise Exception("PDF vazio")
            texto = pdf.pages[0].extract_text() or ""
    except Exception as e:
        raise Exception(f"Erro ao ler PDF: {e}")

    texto = texto.replace("\xa0", " ")
    texto = separar_texto_colado(texto)

    # 1. Extração da Data (Mês de Apuração)
    match_periodo = re.search(r"Per[ií]odo de Apuraç[ãa]o:.*?(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE)
    if not match_periodo:
        match_periodo = re.search(r"Per[ií]odo de Apuraç[ãa]o:.*?(\d{2}/\d{4})", texto, re.IGNORECASE)

    if not match_periodo:
        raise Exception("Período de Apuração não encontrado.")

    data_str = match_periodo.group(1)
    if len(data_str) > 7:
        dt_pa = datetime.strptime(data_str, "%d/%m/%Y")
    else:
        dt_pa = datetime.strptime(data_str, "%m/%Y")

    mes_pa, ano_pa = dt_pa.month, dt_pa.year

    # 2. Extração do RPA (Âncora RPA -> RBT12)
    valor_rpa = 0.0

    idx_rpa = texto.find("(RPA)")
    if idx_rpa == -1: idx_rpa = texto.find("Receita Bruta do PA")

    idx_rbt12 = texto.find("(RBT12)")

    if idx_rpa != -1:
        if idx_rbt12 != -1 and idx_rbt12 > idx_rpa:
            trecho_rpa = texto[idx_rpa:idx_rbt12]
        else:
            trecho_rpa = texto[idx_rpa: idx_rpa + 200]

        vals = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", trecho_rpa)
        if vals:
            valor_rpa = max(parse_num(v) for v in vals)

    # 3. Extração do RBT12 Oficial
    valor_rbt12 = 0.0
    idx_rbt12_start = texto.find("(RBT12)")
    idx_end_rbt12 = texto.find("(RBT12p)")
    if idx_end_rbt12 == -1: idx_end_rbt12 = texto.find("(RBA)")

    if idx_rbt12_start != -1:
        if idx_end_rbt12 != -1 and idx_end_rbt12 > idx_rbt12_start:
            trecho_rbt12 = texto[idx_rbt12_start:idx_end_rbt12]
        else:
            trecho_rbt12 = texto[idx_rbt12_start: idx_rbt12_start + 200]

        vals_rbt = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", trecho_rbt12)
        if vals_rbt:
            valor_rbt12 = max(parse_num(v) for v in vals_rbt)

    # 4. Extração do Histórico
    receitas = {}
    inicio = texto.find("2.2.1)")
    fim = texto.find("2.2.2)")

    if inicio == -1: inicio = texto.find("Receitas Brutas Anteriores")

    if inicio != -1:
        bloco = texto[inicio:fim] if fim != -1 else texto[inicio:]
        datas = re.findall(r"(\d{2}/\d{4})", bloco)
        valores = re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", bloco)

        qtd = min(len(datas), len(valores))
        for i in range(qtd):
            receitas[datas[i]] = parse_num(valores[i])

    if valor_rpa > 0:
        receitas[f"{mes_pa:02d}/{ano_pa}"] = valor_rpa

    return mes_pa, ano_pa, valor_rpa, valor_rbt12, receitas


# ----------------- CÁLCULO VIA BANCO (ENCADEADO) -----------------
def get_faturamento_tasks(emitter_oid, mes, ano):
    """
    Busca notas emitidas (db.tasks) de um mês específico.
    Filtra pela DATA DE COMPETÊNCIA (ex: '2025-11-20').
    """
    start_str = f"{ano}-{mes:02d}-01"

    if mes == 12:
        end_str = f"{ano + 1}-01-01"
    else:
        end_str = f"{ano}-{mes + 1:02d}-01"

    pipeline = [
        {
            "$match": {
                "emitter_id": str(emitter_oid),
                "competencia": {"$gte": start_str, "$lt": end_str},
                "status": "accepted",
                "type": "emit_nfse"
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$valor"}}}
    ]
    result = list(db.tasks.aggregate(pipeline))
    return result[0]["total"] if result else 0.0


def calcular_v1_automatico(emitter_oid, mes_comp, ano_comp):
    """
    Reconstrói o RBT12 somando os 12 meses anteriores.
    Se faltar dado no histórico (ex: Mês 11 não tem PDF), busca no banco.
    """
    ultimo_registro = db.aliquotas.find_one(
        {"emitter_id": emitter_oid},
        sort=[("ano", -1), ("mes", -1)]
    )

    historico_acumulado = ultimo_registro.get("receitas_12m", {}) if ultimo_registro else {}

    # Busca faturamento do mês atual (pode ser 0 se for inicio de mês)
    val_pa = get_faturamento_tasks(emitter_oid, mes_comp, ano_comp)
    chave_pa = f"{mes_comp:02d}/{ano_comp}"
    historico_acumulado[chave_pa] = val_pa

    rbt12_original = 0.0
    dt_cursor = datetime(ano_comp, mes_comp, 1) - timedelta(days=1)

    for _ in range(12):
        m, y = dt_cursor.month, dt_cursor.year
        chave = f"{m:02d}/{y}"

        val = historico_acumulado.get(chave)

        # SE NÃO TIVER NO HISTÓRICO, VAI NO BANCO (Ex: Busca Nov/25 nas Tasks)
        if val is None or val == 0:
            val = get_faturamento_tasks(emitter_oid, m, y)
            historico_acumulado[chave] = val

        rbt12_original += val
        dt_cursor = dt_cursor.replace(day=1) - timedelta(days=1)

    rbt12_original = round(rbt12_original, 2)
    V1 = rbt12_original

    return {
        "V1": V1,
        "mes_pa": mes_comp,
        "ano_pa": ano_comp,
        "rpa_pa": val_pa,
        "receitas_hist": historico_acumulado,
        "passo_a_passo": {
            "RBT12_Calculado_Auto": rbt12_original
        }
    }


# ----------------- ROTA PRINCIPAL -----------------
@router.post("/processar")
async def processar_pgdas(emitterId: str = Form(...), file: UploadFile = File(None),
                          current_user: UserInDB = Depends(get_current_user)):
    try:
        emitter_oid = ObjectId(emitterId)
    except:
        raise HTTPException(status_code=400, detail="EmitterId inválido.")

    user_id = ObjectId(current_user.id)
    emitter = db.emitters.find_one({"_id": emitter_oid, "user_id": user_id})
    if not emitter:
        raise HTTPException(status_code=404, detail="Emissor não encontrado.")

    now = datetime.utcnow()

    # --- A: UPLOAD PDF ---
    if file:
        try:
            mes_apuracao, ano_apuracao, rpa_apuracao, rbt12_oficial, receitas_hist = extrair_dados_pgdas(file)

            if mes_apuracao == 12:
                mes_vigencia = 1
                ano_vigencia = ano_apuracao + 1
            else:
                mes_vigencia = mes_apuracao + 1
                ano_vigencia = ano_apuracao

            dt_target_minus_12 = datetime(ano_apuracao - 1, mes_apuracao, 1)
            val_minus_12 = get_receita_data(dt_target_minus_12.month, dt_target_minus_12.year, receitas_hist)

            if rbt12_oficial > 0:
                V1 = rbt12_oficial - val_minus_12 + rpa_apuracao
                metodo = "Oficial_Ajustado"
            else:
                rbt12_calc = 0.0
                dt_cursor = datetime(ano_apuracao, mes_apuracao, 1)
                for _ in range(12):
                    m, y = dt_cursor.month, dt_cursor.year
                    rbt12_calc += get_receita_data(m, y, receitas_hist)
                    dt_cursor = dt_cursor.replace(day=1) - timedelta(days=1)
                V1 = rbt12_calc
                metodo = "Calculado_Manual_12m"

            V1 = round(V1, 2)
            fonte = "pgdas_pdf"

            dados_finais = {
                "mes_salvar": mes_vigencia,
                "ano_salvar": ano_vigencia,
                "rbt12": V1,
                "rpa_pa": rpa_apuracao,
                "receitas_hist": receitas_hist,
                "passo_a_passo": {
                    "Origem_Apuracao": f"{mes_apuracao}/{ano_apuracao}",
                    "RBT12_Base_PDF": rbt12_oficial,
                    "Metodo": metodo
                }
            }

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao ler PDF: {e}")

    # --- B: AUTOMÁTICO (SEM ARQUIVO) - VIA ROTA MANUAL ---
    else:
        dt_comp = now
        dados = calcular_v1_automatico(emitter_oid, dt_comp.month, dt_comp.year)

        fonte = "automatico_banco"
        dados_finais = {
            "mes_salvar": dados["mes_pa"],
            "ano_salvar": dados["ano_pa"],
            "rbt12": dados["V1"],
            "rpa_pa": dados["rpa_pa"],
            "receitas_hist": dados["receitas_hist"],
            "passo_a_passo": dados["passo_a_passo"]
        }

    V1 = dados_finais["rbt12"]

    faixa_encontrada = None
    for faixa in TABELA_ANEXO_III:
        min_v, max_v, aliq_nominal, deducao_valor = faixa
        if min_v <= V1 <= max_v:
            faixa_encontrada = faixa
            break

    if not faixa_encontrada:
        faixa_encontrada = TABELA_ANEXO_III[-1] if V1 > TABELA_ANEXO_III[-1][1] else (0, 0, 0, 0)

    _, _, aliq_nominal, deducao = faixa_encontrada

    aliquota_efetiva = 0.0
    if V1 > 0 and aliq_nominal > 0:
        V2 = V1 * aliq_nominal
        V3 = V2 - deducao
        aliquota_efetiva = round(V3 / V1, 6)

    # CORREÇÃO VISUAL RPA: Busca o mês anterior (Novembro) para exibir
    dt_ref_rpa = now.replace(day=1) - timedelta(days=1)
    rpa_referencia = get_faturamento_tasks(emitter_oid, dt_ref_rpa.month, dt_ref_rpa.year)

    # Se a fonte for PDF, usa o RPA do PDF. Se for automático, usa a referência.
    rpa_final = dados_finais["rpa_pa"] if fonte == "pgdas_pdf" else rpa_referencia

    doc = {
        "user_id": user_id,
        "emitter_id": emitter_oid,
        "mes": dados_finais["mes_salvar"],
        "ano": dados_finais["ano_salvar"],
        "rbt12": V1,
        "rpa_mes": rpa_final,
        "receitas_12m": dados_finais["receitas_hist"],
        "aliquota": aliquota_efetiva,
        "aliquota_base": aliq_nominal,
        "deducao": deducao,
        "fonte": fonte,
        "created_at": now,
        "passo_a_passo": dados_finais["passo_a_passo"]
    }

    db.aliquotas.update_one(
        {"emitter_id": emitter_oid, "mes": doc["mes"], "ano": doc["ano"]},
        {"$set": doc},
        upsert=True
    )

    return JSONResponse({
        "status": "ok",
        "data": {
            "aliquota": aliquota_efetiva,
            "rbt12": V1,
            "rpa_mes": rpa_final,
            "mes_pa": doc["mes"],
            "ano_pa": doc["ano"],
            "fonte": fonte
        }
    })


# --- GETs ---
@router.get("/atuais")
async def listar_aliquotas(current_user: UserInDB = Depends(get_current_user)):
    user_id = ObjectId(current_user.id)
    pipeline = [{"$match": {"user_id": user_id}}, {"$sort": {"ano": -1, "mes": -1}}]
    aliquotas_db = list(db.aliquotas.aggregate(pipeline))
    aliquotas_limpas = []
    for a in aliquotas_db:
        a["_id"] = str(a["_id"])
        if "emitter_id" in a: a["emitter_id"] = str(a["emitter_id"])
        if "user_id" in a: del a["user_id"]
        if "created_at" in a: del a["created_at"]
        if "receitas_12m" in a: del a["receitas_12m"]
        if "passo_a_passo" in a: del a["passo_a_passo"]
        aliquotas_limpas.append(a)
    return aliquotas_limpas


@router.get("/atual/{emitter_id}")
async def get_aliquota_atual(emitter_id: str, current_user: UserInDB = Depends(get_current_user)):
    try:
        emitter_oid = ObjectId(emitter_id)
    except:
        raise HTTPException(status_code=400, detail="ID inválido")
    user_id = ObjectId(current_user.id)
    if not db.emitters.find_one({"_id": emitter_oid, "user_id": user_id}): return {"aliquota": None}
    aliq = db.aliquotas.find_one({"emitter_id": emitter_oid}, sort=[("ano", -1), ("mes", -1)])
    if not aliq: return {"aliquota": None}
    return {
        "aliquota": aliq.get("aliquota"),
        "mes": aliq.get("mes"),
        "ano": aliq.get("ano"),
        "rbt12": aliq.get("rbt12"),
        "rpa_mes": aliq.get("rpa_mes"),
    }


# --- SCHEDULER ---
def tarefa_recalcular_aliquotas_mensais():
    print(f"[SCHEDULER] Iniciando recálculo mensal: {datetime.now()}")
    emissores = list(db.emitters.find({"ativo": {"$ne": False}}))
    count = 0
    now = datetime.utcnow()

    # Scheduler calcula a alíquota para o MÊS ATUAL (Vigência - Ex: Dezembro)
    mes_target = now.month
    ano_target = now.year

    # Calcula data de referência do RPA (Mês anterior - Ex: Novembro)
    dt_ref_rpa = now.replace(day=1) - timedelta(days=1)

    print(f"[SCHEDULER] Alvo do cálculo (Vigência): {mes_target}/{ano_target}")

    for emissor in emissores:
        try:
            emitter_oid = emissor["_id"]
            user_id = emissor.get("user_id")
            if not user_id: continue

            existente = db.aliquotas.find_one({
                "emitter_id": emitter_oid,
                "mes": mes_target,
                "ano": ano_target
            })
            if existente and existente.get("fonte") == "pgdas_pdf":
                continue

            # Calcula usando dados do banco
            dados = calcular_v1_automatico(emitter_oid, mes_target, ano_target)
            V1 = dados["V1"]

            # --- CORREÇÃO DE EXIBIÇÃO: Pega o RPA do Mês ANTERIOR para salvar ---
            # Isso garante que a tabela mostre R$ 84k e não R$ 0,00
            rpa_referencia = get_faturamento_tasks(emitter_oid, dt_ref_rpa.month, dt_ref_rpa.year)

            faixa_encontrada = None
            for faixa in TABELA_ANEXO_III:
                min_v, max_v, aliq_nominal, deducao_valor = faixa
                if min_v <= V1 <= max_v:
                    faixa_encontrada = faixa
                    break
            if not faixa_encontrada:
                faixa_encontrada = TABELA_ANEXO_III[-1] if V1 > TABELA_ANEXO_III[-1][1] else (0, 0, 0, 0)

            _, _, aliq_nominal, deducao = faixa_encontrada
            aliquota_efetiva = 0.0
            if V1 > 0 and aliq_nominal > 0:
                V2 = V1 * aliq_nominal
                V3 = V2 - deducao
                aliquota_efetiva = round(V3 / V1, 6)

            doc = {
                "user_id": user_id,
                "emitter_id": emitter_oid,
                "mes": dados["mes_pa"],  # Mês 12
                "ano": dados["ano_pa"],
                "rbt12": V1,
                "rpa_mes": rpa_referencia,  # SALVA O RPA DE NOVEMBRO AQUI
                "receitas_12m": dados["receitas_hist"],
                "aliquota": aliquota_efetiva,
                "aliquota_base": aliq_nominal,
                "deducao": deducao,
                "fonte": "scheduler_automatico",
                "created_at": now,
                "passo_a_passo": dados["passo_a_passo"]
            }

            db.aliquotas.update_one(
                {"emitter_id": emitter_oid, "mes": dados["mes_pa"], "ano": dados["ano_pa"]},
                {"$set": doc},
                upsert=True
            )
            count += 1

        except Exception as e:
            print(f"[SCHEDULER] Erro emissor {emissor.get('razao_social')}: {e}")

    print(f"[SCHEDULER] Finalizado. {count} calculados.")
