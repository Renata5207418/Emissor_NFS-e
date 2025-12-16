from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from db import db
from models import User, UserCreate, UserInDB, Token
from utils import verify_password, get_password_hash, serialize_doc
from dotenv import load_dotenv
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

# --- Configurações de Ambiente ---
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24h
RESET_TOKEN_EXPIRE_MINUTES = 30        # Token de reset dura 30 min
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDER_EMAIL="a.automacao3@gmail.com"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

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
    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    message = Mail(
        from_email=SENDER_EMAIL,
        to_emails=to_email,
        subject='Recuperação de Senha',
        html_content=f"""
        <strong>Redefinição de Senha</strong><br><br>
        Clique no link para criar uma nova senha:<br>
        <a href="{reset_link}">Redefinir Minha Senha</a><br><br>
        Link válido por 30 minutos.
        """
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"Email enviado! Status Code: {response.status_code}")
        return True
    except Exception as e:
        print("❌ ERRO SENDGRID:")
        if hasattr(e, 'body'):
            print(e.body)
        else:
            print(e)
        return False


# --- Endpoints ---

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
    # Verifica se o usuário existe
    user = db.users.find_one({"email": email})
    if not user:
        # Retorna sucesso mesmo se não existir (segurança)
        return {"msg": "Se o email estiver cadastrado, um link para redefinição de senha será enviado."}

    # Gera token e envia email
    token = create_reset_token(email)
    if send_reset_email(email, token):
        return {"msg": "Email enviado com sucesso."}
    else:
        raise HTTPException(status_code=500, detail="Falha ao enviar email.")


@router.post("/reset-password")
async def reset_password(token: str = Body(...), new_password: str = Body(...)):
    try:
        # Decodifica e valida o token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")

        if email is None or token_type != "reset":
            raise HTTPException(status_code=400, detail="Token inválido")

    except JWTError:
        raise HTTPException(status_code=400, detail="Token expirado ou inválido")

    # Verifica usuário no banco
    user = db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Atualiza a senha
    hashed_password = get_password_hash(new_password)
    db.users.update_one({"email": email}, {"$set": {"hashed_password": hashed_password}})

    return {"msg": "Senha alterada com sucesso."}
