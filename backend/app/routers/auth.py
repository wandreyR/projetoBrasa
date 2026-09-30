from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import verificar_senha, criar_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login", response_model=schemas.TokenOut)
def login(dados: schemas.LoginIn, db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.email == dados.email).first()
    if not usuario or not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
        )
    if not usuario.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário desativado")

    token = criar_token(usuario)
    return schemas.TokenOut(access_token=token, nome=usuario.nome, cargo=usuario.cargo)


@router.get("/me", response_model=schemas.UsuarioOut)
def me(usuario_atual: models.Usuario = Depends(get_current_user)):
    return usuario_atual
