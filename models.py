from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Literal



# ----------------- AUTENTICAÇÃO E USUÁRIOS -----------------
class Token(BaseModel):
    access_token: str
    token_type: str

class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: str = Field(alias="_id")

class UserInDB(User):
    hashed_password: str

# ----------------- EMISSOR -----------------
class EmitterBase(BaseModel):
    razaoSocial: str
    cnpj: str
    inscricaoMunicipal: Optional[str] = None
    regimeTributacao: Optional[
        Literal["Simples Nacional", "Lucro Presumido", "Lucro Real", "MEI"]
    ] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    codigoIbge: Optional[str] = None
    certificado_path: Optional[str] = None
    senha_certificado: Optional[str] = None
    validade_certificado: Optional[str] = None
    organization_id: Optional[str] = None # Injetado pelo backend

class EmitterUpdate(EmitterBase):
    razaoSocial: Optional[str] = None
    cnpj: Optional[str] = None

# ----------------- CLIENTE -----------------
class ClientBase(BaseModel):
    nome: Optional[str] = None
    documento: Optional[str] = None
    cnpj: Optional[str] = None
    cpf: Optional[str] = None
    email: Optional[EmailStr] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    codigoIbge: Optional[str] = None
    emissores_ids: List[str] = Field(default_factory=list)
    organization_id: Optional[str] = None
    ativo: bool = True

class ClientCreate(ClientBase):
    nome: str

class ClientUpdate(ClientBase):
    pass
# ------------------- PREVIEW / DRAFTS -------------------
class NotaPreviewItemIn(BaseModel):
    """
    O frontend te envia exatamente o que veio da prévia ok=true.
    Esses campos batem com o que sua /notas/preview já retorna.
    """
    index: Optional[int] = None
    ok: bool = True
    emitterId: str
    clienteId: str
    cpf_cnpj: str
    cliente_nome: Optional[str] = None

    valor: float
    descricao: str
    competencia: str
    cod_servico: str
    aliquota: float
    municipio_ibge: Optional[str] = None
    pais_prestacao: str = "BRASIL"
    iss_retido: Optional[bool] = None
    dataEmissao: Optional[str] = None

class DraftOrigem(BaseModel):
    source: str = Field(default="planilha", description="'planilha' ou 'manual'")
    preview_index: Optional[int] = None
    file_name: Optional[str] = None

class TaskDraftCreate(BaseModel):
    emitterId: str
    item: NotaPreviewItemIn
    origem: Optional[DraftOrigem] = None
    idempotency_key: Optional[str] = None   # opcional para evitar duplicidade via frontend

class TaskDraftUpdate(BaseModel):
    """
    Permite ajustes manuais antes de emitir.
    Qlq campo omitido não é atualizado.
    """
    valor: Optional[float] = None
    descricao: Optional[str] = None
    competencia: Optional[str] = None
    cod_servico: Optional[str] = None
    aliquota: Optional[float] = None
    municipio_ibge: Optional[str] = None
    pais_prestacao: Optional[str] = None
    iss_retido: Optional[bool] = None


# ----------------- ALÍQUOTA / PGDAS -----------------
class AliquotaBase(BaseModel):
    emitter_id: str
    ano: int
    mes: int
    rbt12: float
    rpa_mes: float
    aliquota: float
    aliquota_base: float
    deducao: float
    created_at: Optional[str] = None


class AliquotaIn(AliquotaBase):
    pass


class AliquotaOut(AliquotaBase):
    id: str = Field(alias="_id")
