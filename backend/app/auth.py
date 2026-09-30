import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from . import models

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "chave_insegura_trocar_em_producao")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha_plana: str, senha_hash: str) -> bool:
    return pwd_context.verify(senha_plana, senha_hash)


def criar_token(usuario: models.Usuario) -> str:
    expira_em = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(usuario.id),
        "nome": usuario.nome,
        "cargo": usuario.cargo.value,
        "exp": expira_em,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def usuario_do_token(token: str, db: Session) -> Optional[models.Usuario]:
    """Valida o JWT e retorna o usuário ativo correspondente, ou None.

    Separado de get_current_user para ser reaproveitado no WebSocket,
    onde o token chega por query string e não pelo header Authorization.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        usuario_id = int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        return None

    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None or not usuario.ativo:
        return None
    return usuario


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.Usuario:
    usuario = usuario_do_token(token, db)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas ou expiradas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario


def exigir_admin(usuario: models.Usuario = Depends(get_current_user)) -> models.Usuario:
    """Libera a rota só para o dono/gerente (cargo admin)."""
    if usuario.cargo != models.Cargo.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao dono/gerente",
        )
    return usuario
