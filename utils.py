from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.fernet import Fernet
from fastapi import HTTPException
from datetime import datetime
from passlib.context import CryptContext
import json
from lxml import etree as ET
import gzip
from pymongo import ReturnDocument
from bson import ObjectId
import os
import re
import base64
from weasyprint import HTML
import unicodedata
from dotenv import load_dotenv

load_dotenv()

# --- Segurança ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise RuntimeError("ENCRYPTION_KEY não definida no ambiente!")
fernet = Fernet(ENCRYPTION_KEY.encode())


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def encrypt_data(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    return fernet.decrypt(encrypted_data.encode()).decode()


def gerar_dpsXmlGZipB64(xml_string: str) -> str:
    """
    Compacta e codifica o XML já assinado.
    """
    xml_bytes = xml_string.encode("utf-8")
    compressed_data = gzip.compress(xml_bytes)
    return base64.b64encode(compressed_data).decode("utf-8")


def sanitize_document(value: str) -> str:
    return re.sub(r"\D", "", value) if value else value


def serialize_doc(doc):
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        new_doc = {}
        for k, v in doc.items():
            if isinstance(v, ObjectId):
                new_doc[k] = str(v)
            else:
                new_doc[k] = serialize_doc(v)
        return new_doc
    return doc


def extrair_validade_certificado(filepath: str, senha: str) -> str:
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        _, certificate, _ = pkcs12.load_key_and_certificates(
            data, senha.encode() if senha else None
        )
        if not certificate:
            raise HTTPException(status_code=400, detail="Certificado inválido")
        return certificate.not_valid_after.strftime("%Y-%m-%d")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler certificado: {str(e)}")


def identificar_documento(doc: str):
    doc = sanitize_document(doc)
    if len(doc) == 11:
        return "cpf", doc
    elif len(doc) == 14:
        return "cnpj", doc
    else:
        raise HTTPException(status_code=400, detail="Documento inválido")


def to_float(v):
    if v is None or v == "":
        return None
    s = str(v).strip().replace("%", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".") if s.count(",") == 1 and s.count(".") > 1 else s
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


def find_cliente_by_doc(db, doc: str):
    d = sanitize_document(doc or "")
    if len(d) == 11:
        return db.clients.find_one({"cpf": d})
    if len(d) == 14:
        return db.clients.find_one({"cnpj": d})
    return None


def next_dps(db, emitter_id: str, serie: str = "1"):
    try:
        serie_num = int(serie)
    except ValueError:
        raise ValueError("Série do DPS deve ser numérica")
    serie_str = str(serie_num).zfill(5)

    key = f"{emitter_id}|{serie_str}"
    doc = db.dps_counters.find_one_and_update(
        {"_id": key},
        {
            "$inc": {"next": 1},
            "$setOnInsert": {"emitterId": emitter_id, "serie": serie_str},
            "$set": {"updatedAt": datetime.utcnow()},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    numero = int(doc.get("next", 1))
    return {"serie": serie_str, "numero": numero}


def normalize_label(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s


def canonical_from_label(label: str) -> str:
    s = normalize_label(label)
    s_no_paren = re.sub(r"\s*\(.*?\)\s*", "", s).strip()
    candidates = {s, s_no_paren, s_no_paren.replace("/", " "), s_no_paren.replace("/", ""), s_no_paren.replace("  ", " ")}
    mapping = {
        "cpf cnpj": "cpf_cnpj", "cpf/cnpj": "cpf_cnpj", "cpf_cnpj": "cpf_cnpj",
        "valor": "valor", "valor 0.000,00": "valor",
        "descricao": "descricao", "descricao do servico": "descricao",
        "competencia": "competencia", "data de emissao": "competencia", "data emissao": "competencia",
        "ctn": "cod_servico", "ctn cod. do servico": "cod_servico", "cod servico": "cod_servico", "codigo de servico": "cod_servico",
        "aliquota": "aliquota", "aliquota 2% ou 0,02": "aliquota",
        "municipio ibge": "municipio_ibge", "codigo ibge": "municipio_ibge", "municipio": "municipio_ibge",
        "pais da prestacao": "pais_prestacao", "pais prestacao": "pais_prestacao",
        "iss retido": "iss_retido",
    }
    for cand in candidates:
        if cand in mapping:
            return mapping[cand]
    if "cpf" in s and "cnpj" in s: return "cpf_cnpj"
    if "descricao" in s: return "descricao"
    if "emissao" in s or "competencia" in s: return "competencia"
    if "ctn" in s or "servico" in s: return "cod_servico"
    if "aliquota" in s: return "aliquota"
    if "ibge" in s: return "municipio_ibge"
    if "pais" in s: return "pais_prestacao"
    if "iss" in s and "retido" in s: return "iss_retido"
    return s_no_paren


def parse_nfse_response(raw: str) -> dict:
    out = {
        "success": False,
        "protocolo": None,
        "numero_nfse": None,
        "codigo": None,
        "mensagem": None,
        "erros": [],
        "valor": None,
        "bruto": raw or "",
    }

    if not raw:
        return out

    # JSON
    try:
        data = json.loads(raw)
        get = lambda *keys: next((str(data.get(k)) for k in keys if data.get(k) not in (None, "")), None)
        out["protocolo"]   = get("protocolo", "numeroProtocolo", "nProtocolo", "protocoloEnvio")
        out["numero_nfse"] = get("numeroNfse", "nNFSe", "nfse", "numeroNFSe")
        out["codigo"]      = get("codigo", "cod", "codigoRetorno", "status", "statusCode")
        out["mensagem"]    = get("mensagem", "message", "descricao", "detalhe")
        out["valor"]       = data.get("valor") or data.get("valorServico")
        errs = data.get("erros") or data.get("errosValidacao") or data.get("errors") or []
        if isinstance(errs, dict):
            errs = [": ".join([k, str(v)]) for k, v in errs.items()]
        elif isinstance(errs, list):
            errs = [str(e.get("mensagem") or e.get("message") or e) for e in errs]
        else:
            errs = [str(errs)]
        out["erros"] = [e for e in errs if e]
        out["success"] = bool(out["numero_nfse"] or out["protocolo"]) and not out["erros"]
        return out
    except Exception:
        pass

    # XML
    try:
        root = ET.fromstring(raw.encode("utf-8") if isinstance(raw, str) else raw)
        def x(tag): return root.xpath(f".//*[local-name()='{tag}']")
        def text_first(nodes): return nodes[0].text.strip() if nodes and nodes[0].text else None

        out["protocolo"]   = text_first(x("protocolo")) or text_first(x("numeroProtocolo")) or text_first(x("nProtocolo"))
        out["numero_nfse"] = text_first(x("numeroNfse")) or text_first(x("nNFSe")) or text_first(x("NumeroNFSe"))
        out["codigo"]      = text_first(x("codigo")) or text_first(x("codigoRetorno")) or text_first(x("status"))
        out["mensagem"]    = text_first(x("mensagem")) or text_first(x("descricao")) or text_first(x("message"))

        # 🔹 inclui vServ
        val_node = x("valorServicos") or x("valorServico") or x("valor") or x("vServ")
        if val_node:
            try:
                out["valor"] = float(val_node[0].text.strip().replace(",", "."))
            except Exception:
                pass

        erros_nodes = x("erros") or x("Erros") or x("ListaErros")
        erros = []
        for en in erros_nodes:
            msgs = en.xpath(".//*[local-name()='mensagem' or local-name()='descricao' or local-name()='message']/text()")
            erros.extend([m.strip() for m in msgs if m and m.strip()])
        if not erros:
            for en in x("erro"):
                t = (en.text or "").strip()
                if t:
                    erros.append(t)
        out["erros"] = erros
        out["success"] = bool(out["numero_nfse"] or out["protocolo"]) and not out["erros"]
        return out
    except Exception:
        return out


def extract_final_xml(raw_resp: str) -> str | None:
    """
    Extrai o XML final (CompNFSe ou NFSe) do retorno bruto da SEFIN.
    """
    if not raw_resp:
        return None
    # tenta localizar a estrutura final
    m = re.search(r"(<\?xml.*?</CompNFSe>)", raw_resp, re.DOTALL)
    if not m:
        m = re.search(r"(<\?xml.*?</NFSe>)", raw_resp, re.DOTALL)
    return m.group(1) if m else None


def xml_to_pdf(xml_str: str) -> bytes:
    """
    Converte um XML de NFS-e (simples) em PDF renderizado via HTML (WeasyPrint).
    Gera layout básico para exibição legível.
    """
    if not xml_str:
        return b""

    # Extrai campos principais para visualização simples
    def _extract(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml_str)
        return m.group(1).strip() if m else "-"

    numero = _extract("nNFSe") or _extract("nDPS")
    prestador = _extract("CNPJ") or _extract("CPF")
    tomador = _extract("xNome")
    valor = _extract("vServ") or "-"
    competencia = _extract("dCompet") or "-"

    html = f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
          h1 {{ color: #042c4e; }}
          .info {{ margin-top: 10px; }}
          .label {{ font-weight: bold; }}
          .box {{ border: 1px solid #ccc; padding: 20px; margin-top: 20px; border-radius: 8px; }}
        </style>
      </head>
      <body>
        <h1>Nota Fiscal de Serviços Eletrônica (NFS-e Nacional)</h1>
        <div class="box">
          <div class="info"><span class="label">Número:</span> {numero}</div>
          <div class="info"><span class="label">Prestador:</span> {prestador}</div>
          <div class="info"><span class="label">Tomador:</span> {tomador}</div>
          <div class="info"><span class="label">Competência:</span> {competencia}</div>
          <div class="info"><span class="label">Valor:</span> R$ {valor}</div>
        </div>
        <p style="margin-top:30px; font-size: 12px; color:#777;">
          Documento gerado automaticamente a partir do XML da NFS-e Nacional.
        </p>
      </body>
    </html>
    """

    pdf_bytes = HTML(string=html).write_pdf()
    return pdf_bytes


def encode_pdf_base64(pdf_bytes: bytes) -> str:
    """Codifica PDF em base64 para salvar no banco (string)."""
    return base64.b64encode(pdf_bytes).decode("utf-8")


def nfse_gzip_b64_to_xml(gz_b64: str) -> str | None:
    """Descompacta um nfseXmlGZipB64 (base64+gzip) em XML (str)."""
    try:
        raw = base64.b64decode(gz_b64)
        return gzip.decompress(raw).decode("utf-8", errors="replace")
    except Exception:
        return None


def is_dps_repetida(receipt):
    """
    Detecta erro E0014 em diferentes formatos que podem vir no campo 'erros'
    do parse_nfse_response.
    Aceita tanto lista de dicts quanto lista de strings.
    """
    erros = receipt.get("erros") or []

    for e in erros:
        # Caso 1: dict bonitinho: {"Codigo": "E0014", "Descricao": "..."}
        if isinstance(e, dict):
            cod = (e.get("Codigo") or e.get("codigo") or "").strip().upper()
            if cod == "E0014":
                return True

        # Caso 2: string: "{'Codigo': 'E0014', 'Descricao': '...'}" ou parecido
        elif isinstance(e, str):
            if "E0014" in e:
                return True

    # fallback extra: às vezes o parse pode jogar erro só em 'mensagem'
    mensagem = (receipt.get("mensagem") or "").upper()
    if "E0014" in mensagem:
        return True

    return False


def substituir_dps_no_xml(
    xml: str,
    nova_serie: str,
    novo_numero: int,
    emitter_cnpj: str,
    municipio_ibge: str
) -> str:
    """Regera série, número, ID e cLocEmi preservando estrutura."""

    # normalizar campos
    emitter_cnpj = sanitize_document(emitter_cnpj).zfill(14)
    municipio_ibge = str(municipio_ibge).zfill(7)
    serie5 = str(int(nova_serie)).zfill(5)
    numero15 = str(int(novo_numero)).zfill(15)

    # padrão do ID nacional:
    # DPS + cLoc + tpInsc + CNPJ + serie(5) + numero(15)

    tpInsc = "2"  # CNPJ
    novo_id = f"DPS{municipio_ibge}{tpInsc}{emitter_cnpj}{serie5}{numero15}"

    # remover assinatura antiga (se sobrar alguma)
    xml = re.sub(r"<Signature(.|\n|\r)*?</Signature>", "", xml, flags=re.IGNORECASE)

    # substituir ID corretamente no atributo Id=""
    xml = re.sub(r'Id="DPS[^"]+"', f'Id="{novo_id}"', xml)

    # substituir série
    xml = re.sub(r"<serie>.*?</serie>", f"<serie>{serie5}</serie>", xml)

    # substituir número
    xml = re.sub(r"<nDPS>\d+</nDPS>", f"<nDPS>{int(novo_numero)}</nDPS>", xml)

    # substituir cLocEmi (sempre gerar consistente)
    xml = re.sub(r"<cLocEmi>\d+</cLocEmi>", f"<cLocEmi>{municipio_ibge}</cLocEmi>", xml)

    return xml


def remover_assinatura(xml: str) -> str:
    """
    Remove TODAS as assinaturas <Signature> com namespace xmldsig,
    mesmo sem prefixo e mesmo com namespace default.
    """

    try:
        parser = ET.XMLParser(remove_blank_text=True)
        root = ET.fromstring(xml.encode("utf-8"), parser=parser)

        SIGN_NS = "http://www.w3.org/2000/09/xmldsig#"

        # seleciona qualquer tag Signature no namespace DS, com OU sem prefixo
        signatures = root.xpath(
            ".//*[local-name()='Signature' and namespace-uri()='{}']".format(SIGN_NS)
        )

        for sig in signatures:
            parent = sig.getparent()
            if parent is not None:
                parent.remove(sig)

        return ET.tostring(
            root, encoding="utf-8", pretty_print=True, xml_declaration=True
        ).decode("utf-8")

    except Exception:
        # fallback: regex brutal
        return re.sub(
            r"<Signature[\s\S]*?</Signature>",
            "",
            xml,
            flags=re.MULTILINE
        )
