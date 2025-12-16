from lxml import etree as ET
from requests_pkcs12 import post as pkcs12_post, get as pkcs12_get
from requests.exceptions import RequestException
import base64
import time
import gzip

URL_PRODUCAO = "https://sefin.nfse.gov.br/SefinNacional/nfse"
URL_DANFSE = "https://adn.nfse.gov.br/danfse"


def baixar_danfse_pdf(chave_acesso: str, pfx_path: str, pfx_password: str) -> str | None:
    """Faz o download do DANFSe (PDF oficial) do portal ADN."""
    url = f"{URL_DANFSE}/{chave_acesso}"
    print(f"🔍 [DEBUG] Consultando DANFSe: {url}")

    try:
        resp = pkcs12_get(
            url,
            pkcs12_filename=pfx_path,
            pkcs12_password=pfx_password,
            timeout=30,
            verify=True,
        )

        print("🔍 [DEBUG] HTTP STATUS (DANFSe):", resp.status_code)

        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/pdf"):
            pdf_b64 = base64.b64encode(resp.content).decode("ascii")
            print("DANFSe PDF obtido com sucesso.")
            return pdf_b64

        if resp.status_code == 404:
            print("DANFSe ainda não disponível (404).")
        else:
            print("Erro DANFSe:", resp.text[:500])

    except Exception as e:
        print("Erro ao consultar DANFSe:", e)

    return None


def enviar_nfse_pkcs12(dps_b64: str, pfx_path: str, pfx_password: str):
    payload = {"dpsXmlGZipB64": dps_b64}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    resp = pkcs12_post(
        URL_PRODUCAO,
        json=payload,
        headers=headers,
        pkcs12_filename=pfx_path,
        pkcs12_password=pfx_password,
        timeout=30,
        verify=True,
    )

    xml_resp = resp.text or ""
    print("🔍 [DEBUG] HTTP STATUS:", resp.status_code)
    print("🔍 [DEBUG] RAW RESPONSE:")
    print(xml_resp[:1000])

    pdf_base64 = None
    xml_nfse = None
    id_dps = None
    chave_acesso = None

    # --- 1) tenta tratar como JSON (caso 201/400 estruturado) ---
    data = None
    try:
        data = resp.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        id_dps = data.get("idDps") or data.get("idDPS")
        chave_acesso = data.get("chaveAcesso")

        # XML da NFS-e vem em GZIP Base64
        gz_b64 = data.get("nfseXmlGZipB64") or data.get("nfseXmlGzipB64")
        if gz_b64:
            try:
                xml_nfse = gzip.decompress(base64.b64decode(gz_b64)).decode("utf-8", errors="replace")
            except Exception as e:
                print("Falha ao descompactar nfseXmlGZipB64:", e)

        # 🔹 se a nota foi aceita, tenta buscar o DANFSe
        if resp.status_code in (200, 201) and chave_acesso:
            # Tenta até 3 vezes com intervalo de 2 segundos
            max_retries = 3
            for i in range(max_retries):
                print(f"?? Tentativa {i + 1}/{max_retries} de baixar PDF no fluxo imediato...")
                pdf_base64 = baixar_danfse_pdf(chave_acesso, pfx_path, pfx_password)

                if pdf_base64:
                    break  # Sucesso, sai do loop

                # Se falhou, espera um pouco antes de tentar de novo
                time.sleep(2)

        return {
            "status": resp.status_code,
            "body": xml_resp,
            "xml_nfse": xml_nfse,
            "pdf_base64": pdf_base64,
            "id_dps": id_dps,
            "chave_acesso": chave_acesso,
        }

    # --- 2) fallback XML (resposta pura) ---
    try:
        root = ET.fromstring(xml_resp.encode("utf-8"))
        ns = {"ns": root.nsmap.get(None)} if None in root.nsmap else {}

        pdf_el = root.find(".//ns:pdfBase64", ns)
        nfse_el = root.find(".//ns:NFSe", ns)

        if pdf_el is not None and pdf_el.text:
            pdf_base64 = pdf_el.text.strip()
        if nfse_el is not None:
            xml_nfse = ET.tostring(nfse_el, encoding="utf-8").decode("utf-8")

        # 🔹 tenta buscar DANFSe também se tiver chave
        if chave_acesso and not pdf_base64:
            for i in range(3):
                pdf_base64 = baixar_danfse_pdf(chave_acesso, pfx_path, pfx_password)
                if pdf_base64: break
                time.sleep(2)

    except Exception as e:
        print(" Falha ao parsear resposta da NFS-e:", e)

    return {
        "status": resp.status_code,
        "body": xml_resp,
        "xml_nfse": xml_nfse,
        "pdf_base64": pdf_base64,
        "id_dps": id_dps,
        "chave_acesso": chave_acesso,
    }


def enviar_cancelamento_pkcs12(chave_acesso: str, evento_b64_gzip: str, pfx_path: str, pfx_password: str):
    """
    Envia um Pedido de Evento (Cancelamento) para a API Nacional.
    A rota é: POST /nfse/{chaveAcesso}/eventos
    """

    url = f"{URL_PRODUCAO}/{chave_acesso}/eventos"

    payload = {"pedidoRegistroEventoXmlGZipB64": evento_b64_gzip}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    print(f"? [DEBUG] Enviando Cancelamento para: {url}")
    print(f"? [DEBUG] Usando a chave 'pedidoRegistroEventoXmlGZipB64' para o payload.")

    try:
        resp = pkcs12_post(
            url,
            json=payload,
            headers=headers,
            pkcs12_filename=pfx_path,
            pkcs12_password=pfx_password,
            timeout=30,
            verify=True,
        )

        print("? [DEBUG] HTTP STATUS (Cancelamento):", resp.status_code)
        print("? [DEBUG] RAW RESPONSE (Cancelamento):")
        print(resp.text[:1000])

        return resp

    except RequestException as e:
        print(f"Erro ao enviar cancelamento: {e}")
        raise e
