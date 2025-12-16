import base64
import hashlib
from lxml import etree as ET
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"


def assinar_xml(
        xml_input: str | bytes,
        pfx_path: str,
        pfx_password: str,
        tag_to_sign: str = "infDPS"
) -> str:
    """
    Assina a tag <infDPS> do XML da DPS (formato Enveloped),
    conforme padrão NFS-e Nacional (Sefin Nacional),
    mantendo estrutura igual ao XML que valida na SEFIN.

    Modificado para aceitar 'tag_to_sign' (ex: "infDPS" ou "infPedReg").
    """

    # === 1) Carrega chave privada e certificado do PFX ===
    with open(pfx_path, "rb") as f:
        pfx_data = f.read()
    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
        pfx_data, pfx_password.encode() if pfx_password else None
    )

    if private_key is None or certificate is None:
        raise ValueError("PFX inválido: sem chave privada ou certificado.")

    cert_b64 = base64.b64encode(certificate.public_bytes(Encoding.DER)).decode()

    # === 2) Carrega o XML ===
    if isinstance(xml_input, bytes):
        root = ET.fromstring(xml_input)
    else:
        root = ET.fromstring(xml_input.encode("utf-8"))

    ns_nfse = {"ns": NS_NFSE}

    # === 3) Localiza o elemento <infDPS> ou <infPedReg> ===
    # ### Usa a variável 'tag_to_sign'
    target_element = root.find(f"ns:{tag_to_sign}", ns_nfse)
    if target_element is None:
        # ### Erro dinâmico
        raise ValueError(f"Elemento <{tag_to_sign}> não encontrado.")

        # ### Usa 'target_element'
    inf_id = target_element.get("Id")
    if not inf_id:
        # ### Erro dinâmico
        raise ValueError(f"Atributo Id ausente em <{tag_to_sign}>.")

        # === 4) Canonicaliza <infDPS> (ou target) e calcula o DigestValue ===
    # ### Usa 'target_element'
    target_bytes = ET.tostring(target_element, encoding="utf-8")
    target_c14n = ET.tostring(
        ET.fromstring(target_bytes),
        method="c14n",
        exclusive=False,
        with_comments=False,
    )

    # ### Usa 'target_c14n'
    digest = hashlib.sha1(target_c14n).digest()
    digest_b64 = base64.b64encode(digest).decode("utf-8")

    # === 5) Monta a estrutura de assinatura ===
    nsmap = {None: NS_DS}
    Signature = ET.Element("{%s}Signature" % NS_DS, nsmap=nsmap)

    SignedInfo = ET.SubElement(Signature, "{%s}SignedInfo" % NS_DS)
    ET.SubElement(
        SignedInfo,
        "{%s}CanonicalizationMethod" % NS_DS,
        Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    ET.SubElement(
        SignedInfo,
        "{%s}SignatureMethod" % NS_DS,
        Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1",
    )

    Reference = ET.SubElement(SignedInfo, "{%s}Reference" % NS_DS, URI=f"#{inf_id}")
    Transforms = ET.SubElement(Reference, "{%s}Transforms" % NS_DS)
    ET.SubElement(
        Transforms,
        "{%s}Transform" % NS_DS,
        Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature",
    )
    ET.SubElement(
        Transforms,
        "{%s}Transform" % NS_DS,
        Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    ET.SubElement(
        Reference,
        "{%s}DigestMethod" % NS_DS,
        Algorithm="http://www.w3.org/2000/09/xmldsig#sha1",
    )
    ET.SubElement(Reference, "{%s}DigestValue" % NS_DS).text = digest_b64

    # === 6) Canonicaliza SignedInfo e assina ===
    signedinfo_bytes = ET.tostring(SignedInfo, encoding="utf-8")
    signedinfo_c14n_element = ET.fromstring(signedinfo_bytes)
    c14n_signed = ET.tostring(
        signedinfo_c14n_element, method="c14n", exclusive=False, with_comments=False
    )

    signature_raw = private_key.sign(c14n_signed, padding.PKCS1v15(), hashes.SHA1())
    signature_b64 = base64.b64encode(signature_raw).decode("utf-8")

    # === 7) Insere SignatureValue e KeyInfo ===
    ET.SubElement(Signature, "{%s}SignatureValue" % NS_DS).text = signature_b64

    KeyInfo = ET.SubElement(Signature, "{%s}KeyInfo" % NS_DS)
    X509Data = ET.SubElement(KeyInfo, "{%s}X509Data" % NS_DS)
    ET.SubElement(X509Data, "{%s}X509Certificate" % NS_DS).text = cert_b64

    # === 8) Adiciona <ds:Signature> após a tag assinada ===
    # ### Usa 'target_element'
    target_element.addnext(Signature)

    # === 9) Retorna XML final ===
    xml_signed = ET.tostring(root, pretty_print=False, encoding="utf-8", xml_declaration=True)
    return xml_signed.decode("utf-8")
