import os
import sys
from bson import ObjectId
from datetime import datetime, timedelta
from db import db

# --- CONFIGURAÇÃO DO TESTE ---
EMITTER_ID_TESTE = "6911f10babdd1164b09f97b4"
MES_SIMULADO = 10
ANO_SIMULADO = 2025
VALOR_PA_SIMULADO = 122296.08
# --- FIM DA CONFIGURAÇÃO ---

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from routers.aliquota import TABELA_ANEXO_III
except ImportError:
    print("Erro ao importar TABELA_ANEXO_III de routers.aliquota.")
    sys.exit(1)


def calcular_v1_simulado(emitter_oid, mes_pa, ano_pa, rpa_pa):
    """
    Simula o cálculo V1 usando a fórmula PADRÃO do Simples Nacional.
    Retorna todos os dados necessários para o cálculo e salvamento.
    """
    print(f"\n--- Iniciando Simulação (Mês {mes_pa}/{ano_pa}) ---")

    last_aliq_doc = db.aliquotas.find_one(
        {"emitter_id": emitter_oid},
        sort=[("ano", -1), ("mes", -1)]
    )

    if not last_aliq_doc:
        print(f"ERRO: PGDAS base não encontrado em db.aliquotas para {emitter_oid}")
        return None

    historico_base = last_aliq_doc.get("receitas_12m", {})
    print(f"-> Base encontrada: PGDAS de {last_aliq_doc.get('mes')}/{last_aliq_doc.get('ano')}")

    # 1. Calcular RBT12 Original (Soma dos 12 meses anteriores ao Mês 10)
    # Ou seja, 10/2024 até 09/2025
    rbt12_original = 0.0
    dt_cursor = datetime(ano_pa, mes_pa, 1) - timedelta(days=1)  # 30/09/2025

    print("\nBuscando RBT12 Original (baseado no histórico):")
    for i in range(12):
        m, y = dt_cursor.month, dt_cursor.year
        chave = f"{m:02d}/{y}"
        val = historico_base.get(chave, 0.0)
        rbt12_original += val
        dt_cursor = dt_cursor.replace(day=1) - timedelta(days=1)

    rbt12_original = round(rbt12_original, 2)
    print(f"-> Total RBT12 Original (10/24 a 09/25): R$ {rbt12_original:.2f}")

    # 2. Buscar variáveis para a Fórmula V1 (Padrão)
    def get_val_real_hist(delta):
        total_m = (ano_pa * 12 + (mes_pa - 1)) + delta
        y = total_m // 12
        m = (total_m % 12) + 1
        chave = f"{m:02d}/{y}"
        return historico_base.get(chave, 0.0)

    val_pa = rpa_pa
    val_pa_minus_12 = get_val_real_hist(-12)  # Mês 10/2024

    V1 = rbt12_original - val_pa_minus_12 + val_pa
    V1 = round(V1, 2)

    print(f"\n>>> V1 CALCULADO: {V1:.2f} <<<")

    # 3. Construir o novo histórico (11/2024 a 10/2025) para salvar
    # Este será o histórico usado para o cálculo de Novembro
    new_receitas_hist = {}
    dt_cursor_hist = datetime(ano_pa, mes_pa, 1)  # 10/2025
    for _ in range(12):
        m, y = dt_cursor_hist.month, dt_cursor_hist.year
        chave = f"{m:02d}/{y}"

        if m == mes_pa and y == ano_pa:
            val = rpa_pa  # Usa o valor simulado
        else:
            val = historico_base.get(chave, 0.0)  # Usa o histórico antigo

        new_receitas_hist[chave] = val
        dt_cursor_hist = dt_cursor_hist.replace(day=1) - timedelta(days=1)

    return V1, rbt12_original, new_receitas_hist


def calcular_aliquota_final(v1):
    """Retorna todos os dados da faixa e do cálculo V2, V3, V4"""
    faixa_encontrada = None
    for faixa in TABELA_ANEXO_III:
        min_v, max_v, aliq_nominal, deducao_valor = faixa
        if min_v <= v1 <= max_v:
            faixa_encontrada = faixa
            break

    if not faixa_encontrada:
        faixa_encontrada = TABELA_ANEXO_III[-1] if v1 > TABELA_ANEXO_III[-1][1] else (0, 0, 0, 0)

    _, _, aliq_nominal, deducao = faixa_encontrada

    if v1 > 0 and aliq_nominal > 0:
        V2 = v1 * aliq_nominal
        V3 = V2 - deducao
        V4 = V3 / v1
        aliquota_efetiva = round(V4, 6)
    else:
        V2, V3, aliquota_efetiva = 0.0, 0.0, 0.0

    print("\n--- Resultado da Alíquota ---")
    print(f"  Faixa Encontrada: {aliq_nominal * 100}% com dedução de R$ {deducao}")
    print(f"  Alíquota Efetiva Final: {(aliquota_efetiva * 100):.6f}%")

    return aliquota_efetiva, aliq_nominal, deducao, V2, V3


# --- RODA O TESTE ---
if __name__ == "__main__":
    if EMITTER_ID_TESTE == "COLE_O_ID_DO_EMISSOR_AQUI":
        print("Erro: Edite o arquivo 'testar_calculo.py' e defina o EMITTER_ID_TESTE.")
        sys.exit(0)

    emitter_oid = ObjectId(EMITTER_ID_TESTE)

    # 1. Busca o Dono (user_id) do Emissor
    emitter = db.emitters.find_one({"_id": emitter_oid})
    if not emitter or not emitter.get("user_id"):
        print(f"ERRO: Emissor {EMITTER_ID_TESTE} não encontrado ou não possui 'user_id' no banco.")
        sys.exit(0)

    user_id = emitter.get("user_id")
    print(f"Emissor encontrado. Pertence ao usuário: {user_id}")

    # 2. Executa os cálculos
    calculo = calcular_v1_simulado(
        emitter_oid=emitter_oid,
        mes_pa=MES_SIMULADO,
        ano_pa=ANO_SIMULADO,
        rpa_pa=VALOR_PA_SIMULADO
    )

    if not calculo:
        sys.exit(0)  # Sai se não achou PGDAS base

    v1_final, rbt12_orig, new_history = calculo

    aliq_efetiva, aliq_nominal, deducao, v2, v3 = calcular_aliquota_final(v1_final)

    # 3. Confirmação de Segurança
    print("\n--- PRONTO PARA SALVAR NO BANCO ---")
    print(f"  Mês/Ano: {MES_SIMULADO}/{ANO_SIMULADO}")
    print(f"  RBT12 (V1): {v1_final}")
    print(f"  Alíquota: {aliq_efetiva * 100:.6f}%")

    confirm = input("\nVocê confirma o salvamento deste cálculo no banco de dados? (s/n): ").strip().lower()

    if confirm == 's':
        now = datetime.utcnow()
        doc = {
            "user_id": user_id,
            "emitter_id": emitter_oid,
            "mes": MES_SIMULADO,
            "ano": ANO_SIMULADO,
            "rbt12": v1_final,
            "rpa_mes": VALOR_PA_SIMULADO,
            "receitas_12m": new_history,
            "aliquota": aliq_efetiva,
            "aliquota_base": aliq_nominal,
            "deducao": deducao,
            "fonte": "simulacao_manual",  # Fonte
            "created_at": now,
            "passo_a_passo": {
                "RBT12_Original_Soma": rbt12_orig,
                "V1_Calculado": v1_final,
                "V2_ImpostoBruto": round(v2, 2),
                "V3_Liquido": round(v3, 2),
                "V4_AliquotaEfetiva": aliq_efetiva
            }
        }

        # 4. Salva no Banco (Upsert)
        db.aliquotas.update_one(
            {"emitter_id": emitter_oid, "mes": MES_SIMULADO, "ano": ANO_SIMULADO},
            {"$set": doc},
            upsert=True
        )
        print("\n✅ SUCESSO! Alíquota do Mês 10 salva no banco de dados.")
    else:
        print("\n❌ OPERAÇÃO CANCELADA. Nada foi salvo.")
