from lxml import etree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from utils import sanitize_document, to_float
import re

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
RX_ID = re.compile(r"^DPS[0-9]{42}$")  # "DPS" + 42 dígitos


def _map_op_simp_nac(emitter: dict) -> str:
    """Mapa simples para opSimpNac:
       1 = Não Optante; 2 = MEI; 3 = ME/EPP (Simples Nacional)"""
    regime = (emitter.get("regimeTributacao") or "").strip().lower()
    if "mei" in regime:
        return "2"
    if "simples" in regime:
        return "3"
    return "1"


def build_cancelamento_xml(
    emitter_cnpj: str,
    chave_acesso_nota: str,
    justificativa: str,
    tp_amb: str = "1",
    ver_aplic: str = "1.0.230",
    n_ped_reg: str = "001",
    c_motivo: str = "2",
) -> str:
    """
    Monta o XML de Pedido de Registro de Evento de Cancelamento (e101101)
    no layout exigido pelo Sistema Nacional NFS-e.
    """

    emitter_doc = sanitize_document(emitter_cnpj)
    if len(emitter_doc) == 14:
        autor_tag = "CNPJAutor"
    elif len(emitter_doc) == 11:
        autor_tag = "CPFAutor"
    else:
        raise ValueError("Documento do emissor inválido para cancelamento")

    # Id no padrão usado no exemplo funcional:
    # PRE + chNFSe (50) + 101101 (tipo evento cancelamento) + nPedRegEvento (3)
    n_ped_reg = str(n_ped_reg).zfill(3)
    id_evento = f"PRE{chave_acesso_nota}101101{n_ped_reg}"

    dh_evento = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(microsecond=0).isoformat()

    root = ET.Element("pedRegEvento", nsmap={None: NS_NFSE}, versao="1.00")
    inf = ET.SubElement(root, "infPedReg", Id=id_evento)

    ET.SubElement(inf, "tpAmb").text = tp_amb
    ET.SubElement(inf, "verAplic").text = ver_aplic
    ET.SubElement(inf, "dhEvento").text = dh_evento

    ET.SubElement(inf, autor_tag).text = emitter_doc
    ET.SubElement(inf, "chNFSe").text = chave_acesso_nota
    ET.SubElement(inf, "nPedRegEvento").text = n_ped_reg

    # Parte específica do evento de cancelamento (e101101)
    e101101 = ET.SubElement(inf, "e101101")
    ET.SubElement(e101101, "xDesc").text = "Cancelamento de NFS-e"
    ET.SubElement(e101101, "cMotivo").text = str(c_motivo)
    ET.SubElement(e101101, "xMotivo").text = justificativa.strip()[:255]

    return ET.tostring(
        root,
        pretty_print=True,
        encoding="utf-8",
        xml_declaration=True,
    ).decode("utf-8")


def build_nfse_xml(
    emitter: dict,
    client: dict,
    service: dict,
    numero_dps: int,
    serie_dps: str,
    competencia: str,
    pais_prestacao: str = "BRASIL",
    data_emissao: str | None = None,
) -> str:

    # --- cLocEmi: município do prestador ---
    cmun_emi = str(emitter.get("codigoIbge") or "").zfill(7)
    if not cmun_emi.isdigit() or len(cmun_emi) != 7:
        raise ValueError("codigoIbge do emissor inválido para cLocEmi")

    # --- município da prestação  ---
    cmun_prestacao = cmun_emi

    # --- competência AAAA-MM-DD ---
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", competencia):
        raise ValueError("competencia deve estar no formato AAAA-MM-DD")

    # --- documento do prestador + tpInsc ---
    doc_prest = sanitize_document(emitter.get("cnpj", "") or emitter.get("cpf", ""))
    if len(doc_prest) == 14:
        tpInsc = "2"
    elif len(doc_prest) == 11:
        tpInsc = "1"
    else:
        raise ValueError("Documento do prestador inválido")
    nInsc14 = doc_prest.zfill(14)

    # --- série (5) e número (15) no Id ---
    serie5 = f"{int(serie_dps):05d}"
    nDPS15 = f"{int(numero_dps):015d}"
    inf_id = f"DPS{cmun_emi}{tpInsc}{nInsc14}{serie5}{nDPS15}"

    # --- raiz ---
    root = ET.Element("DPS", nsmap={None: NS_NFSE}, versao="1.00")
    inf = ET.SubElement(root, "infDPS", Id=inf_id)

    # --- cabeçalho ---
    if data_emissao:
        try:
            dt = datetime.fromisoformat(data_emissao)
            dh_emi = dt.replace(microsecond=0).isoformat()
        except Exception:
            dt = datetime.now(ZoneInfo("America/Sao_Paulo"))
            dh_emi = (dt - timedelta(seconds=2)).replace(microsecond=0).isoformat()
    else:
        dt = datetime.now(ZoneInfo("America/Sao_Paulo"))
        dh_emi = (dt - timedelta(seconds=2)).replace(microsecond=0).isoformat()

    ET.SubElement(inf, "tpAmb").text = "1"  # 1=Produção
    ET.SubElement(inf, "dhEmi").text = dh_emi
    ET.SubElement(inf, "verAplic").text = "1.0.230"
    ET.SubElement(inf, "serie").text = serie5
    ET.SubElement(inf, "nDPS").text = str(int(numero_dps))
    ET.SubElement(inf, "dCompet").text = competencia
    ET.SubElement(inf, "tpEmit").text = "1"  # Prestador
    ET.SubElement(inf, "cLocEmi").text = cmun_emi

    # --- prestador ---
    prest = ET.SubElement(inf, "prest")
    ET.SubElement(prest, "CNPJ" if tpInsc == "2" else "CPF").text = doc_prest
    if emitter.get("email"):
        ET.SubElement(prest, "email").text = emitter["email"]

    regTrib = ET.SubElement(prest, "regTrib")
    op_simp = _map_op_simp_nac(emitter)
    ET.SubElement(regTrib, "opSimpNac").text = op_simp
    if op_simp == "3":
        ET.SubElement(regTrib, "regApTribSN").text = "1"
    ET.SubElement(regTrib, "regEspTrib").text = "0"

    # --- TOMADOR ---
    if not client.get("nao_identificado"):

        toma = ET.SubElement(inf, "toma")

        doc_toma = sanitize_document(client.get("cnpj") or client.get("cpf") or "")
        if len(doc_toma) == 14:
            ET.SubElement(toma, "CNPJ").text = doc_toma
        elif len(doc_toma) == 11:
            ET.SubElement(toma, "CPF").text = doc_toma
        else:
            raise ValueError("Documento do tomador inválido")

        ET.SubElement(toma, "xNome").text = client.get("nome", "")[:115]

        # ----------------------------
        #  VALIDAÇÃO E HIERARQUIA
        # ----------------------------
        cliente_cmun_raw = str(client.get("codigoIbge") or "").strip()
        cliente_cep_raw = sanitize_document(client.get("cep") or "")

        # 1. Lógica de Bloqueio:
        # Se não tiver IBGE (caso do seu cliente Regional) ou não tiver CEP,
        # as variáveis abaixo dão False e o bloco de endereço inteiro é pulado.
        ibge_ok = cliente_cmun_raw.isdigit() and len(cliente_cmun_raw) == 7
        cep_ok = cliente_cep_raw.isdigit() and len(cliente_cep_raw) == 8

        if ibge_ok and cep_ok:
            end = ET.SubElement(toma, "end")

            # endNac mínimo (OBRIGATÓRIO)
            endNac = ET.SubElement(end, "endNac")
            ET.SubElement(endNac, "cMun").text = cliente_cmun_raw
            ET.SubElement(endNac, "CEP").text = cliente_cep_raw

            # Dados complementares FORA do endNac
            ET.SubElement(end, "xLgr").text = (client.get("logradouro") or "NAO INFORMADO")[:125]
            ET.SubElement(end, "nro").text = (str(client.get("numero")) if client.get("numero") else "S/N")[:60]

            if client.get("complemento"):
                ET.SubElement(end, "xCpl").text = client["complemento"][:60]

            ET.SubElement(end, "xBairro").text = (client.get("bairro") or "NAO INFORMADO")[:60]

    # --- serviço ---
    serv = ET.SubElement(inf, "serv")
    ET.SubElement(ET.SubElement(serv, "locPrest"), "cLocPrestacao").text = cmun_prestacao

    cs = ET.SubElement(serv, "cServ")
    ET.SubElement(cs, "cTribNac").text = str(service["cTribNac"])
    ET.SubElement(cs, "xDescServ").text = service.get("descricao", "")[:1000]

    # --- valores ---
    valores = ET.SubElement(inf, "valores")
    ET.SubElement(ET.SubElement(valores, "vServPrest"), "vServ").text = f"{to_float(service['valor']):.2f}"

    trib = ET.SubElement(valores, "trib")
    tribMun = ET.SubElement(trib, "tribMun")
    ET.SubElement(tribMun, "tribISSQN").text = "1"

    iss_retido = str(service.get("issRetido") or "N").strip().upper() == "S"
    ET.SubElement(tribMun, "tpRetISSQN").text = "2" if iss_retido else "1"

    # pAliq: só envia se não for SN sem retenção
    aliq = service.get("aliquota")
    pode_enviar_aliq = not (op_simp == "3" and not iss_retido)
    if pode_enviar_aliq and aliq not in (None, "", "0", 0, "0.00"):
        aliq_f = float(str(aliq).replace("%", "").replace(",", "."))
        if aliq_f > 1:
            aliq_f /= 100.0
        ET.SubElement(tribMun, "pAliq").text = f"{aliq_f * 100:.2f}"

    totTrib = ET.SubElement(trib, "totTrib")
    if op_simp == "3":
        p_sn = service.get("aliquota")
        if p_sn in (None, ""):
            p_sn_val = 0.0
        else:
            p_sn_val = float(str(p_sn).replace("%", "").replace(",", "."))
        if p_sn_val > 0 and p_sn_val < 1.0:
            p_sn_val = p_sn_val * 100.0
        ET.SubElement(totTrib, "pTotTribSN").text = f"{p_sn_val:.2f}"
    else:
        ET.SubElement(totTrib, "indTotTrib").text = "0"

    return ET.tostring(root, pretty_print=True, encoding="utf-8", xml_declaration=True).decode("utf-8")
