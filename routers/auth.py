from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from db import db
from models import User, UserCreate, UserInDB, Token
from utils import verify_password, get_password_hash, serialize_doc
from dotenv import load_dotenv
import os

# --- NOVAS IMPORTAÇÕES PARA EMAIL (GMAIL) ---
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

# --- Configurações de Ambiente ---
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24h
RESET_TOKEN_EXPIRE_MINUTES = 30  # Token de reset dura 30 min

# Configurações do Gmail (Coloque isso no seu .env)
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
FRONTEND_URL = os.getenv("FRONTEND_URL")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY não definida no ambiente!")

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# --- Funções Auxiliares ---

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_reset_token(email: str):
    data = {"sub": email, "type": "reset"}
    expire = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def send_reset_email(to_email: str, token: str):
    """
    Envia e-mail usando o servidor SMTP do Gmail.
    """
    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    subject = "Recuperação de Senha - Sistema Notas"

    # Corpo do Email em HTML
    html_content = f"""
    <html>
        <body>
            <div style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #333;">Redefinição de Senha</h2>
                <p>Recebemos uma solicitação para redefinir sua senha.</p>
                <p>Clique no botão abaixo para criar uma nova senha:</p>
                <br>
                <a href="{reset_link}" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                    Redefinir Minha Senha
                </a>
                <br><br>
                <p style="font-size: 12px; color: #666;">Este link é válido por 30 minutos.</p>
                <p style="font-size: 12px; color: #666;">Se você não solicitou isso, apenas ignore este e-mail.</p>
            </div>
        </body>
    </html>
    """

    # Configuração da Mensagem
    msg = MIMEMultipart()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))

    try:
        # Conexão com o servidor SMTP do Gmail
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Criptografia TLS

        # Login com a Senha de App (NÃO é a senha normal do Google)
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

        # Envio
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, to_email, text)
        server.quit()

        print(f"? Email enviado com sucesso para {to_email}")
        return True

    except Exception as e:
        print(f"? Erro ao enviar email via Gmail: {e}")
        return False


# --- Endpoints (Mantidos iguais) ---

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception

        user_data = db.users.find_one({"email": email})
        if user_data is None:
            raise credentials_exception

        return UserInDB.parse_obj(serialize_doc(user_data))
    except JWTError:
        raise credentials_exception


@router.get("/users/me", response_model=User)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return current_user


@router.post("/register", response_model=User)
async def register_user(user_in: UserCreate):
    if db.users.find_one({"email": user_in.email}):
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    hashed_password = get_password_hash(user_in.password)
    user_data = {
        "name": user_in.name,
        "email": user_in.email,
        "hashed_password": hashed_password,
        "created_at": datetime.utcnow(),
    }
    result = db.users.insert_one(user_data)
    created_user = db.users.find_one({"_id": result.inserted_id})
    return User.parse_obj(serialize_doc(created_user))


@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_data = db.users.find_one({"email": form_data.username})
    if not user_data or not verify_password(form_data.password, user_data["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )
    access_token = create_access_token(data={"sub": user_data["email"]})
    return {"access_token": access_token, "token_type": "bearer"}


# --- Rotas de Esqueci a Senha ---

@router.post("/forgot-password")
async def forgot_password(email: str = Body(..., embed=True)):
    user = db.users.find_one({"email": email})
    if not user:
        # Segurança: Não avise se o email não existe
        return {"msg": "Se o email estiver cadastrado, um link será enviado."}

    token = create_reset_token(email)

    # Chama a nova função do Gmail
    if send_reset_email(email, token):
        return {"msg": "Email enviado com sucesso."}
    else:
        raise HTTPException(status_code=500, detail="Falha ao enviar email.")


@router.post("/reset-password")
async def reset_password(token: str = Body(...), new_password: str = Body(...)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")

        if email is None or token_type != "reset":
            raise HTTPException(status_code=400, detail="Token inválido")

    except JWTError:
        raise HTTPException(status_code=400, detail="Token expirado ou inválido")

    user = db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    hashed_password = get_password_hash(new_password)
    db.users.update_one({"email": email}, {"$set": {"hashed_password": hashed_password}})

    return {"msg": "Senha alterada com sucesso."}
