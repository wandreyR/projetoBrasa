import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal
from . import models
from .auth import hash_senha
from .routers import cardapio, auth, pedidos, gerencial

app = FastAPI(title="BRASA Pizzaria API", version="1.0.0")

# Libera acesso do frontend estático (abre local ou em outra porta) durante o desenvolvimento.
# Em produção, troque "*" pela URL real do frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cardapio.router)
app.include_router(auth.router)
app.include_router(pedidos.router)
app.include_router(gerencial.router)


def seed_data(db: Session):
    """Popula o banco na primeira execução, se estiver vazio."""

    if db.query(models.Pizza).count() == 0:
        pizzas = [
            models.Pizza(slug="margherita", nome="Margherita", categoria=models.CategoriaPizza.tradicionais,
                         descricao="Molho de tomate, mussarela e manjericão fresco", cor_hex="#C1391F",
                         preco_p=32, preco_m=42, preco_g=52),
            models.Pizza(slug="calabresa", nome="Calabresa", categoria=models.CategoriaPizza.tradicionais,
                         descricao="Molho de tomate, mussarela, calabresa e cebola", cor_hex="#9A2C17",
                         preco_p=34, preco_m=44, preco_g=54),
            models.Pizza(slug="portuguesa", nome="Portuguesa", categoria=models.CategoriaPizza.tradicionais,
                         descricao="Presunto, ovos, cebola, azeitona e mussarela", cor_hex="#C1391F",
                         preco_p=36, preco_m=47, preco_g=58),
            models.Pizza(slug="frango-catupiry", nome="Frango com Catupiry", categoria=models.CategoriaPizza.especiais,
                         descricao="Frango desfiado, catupiry cremoso e milho", cor_hex="#D4A017",
                         preco_p=36, preco_m=47, preco_g=58),
            models.Pizza(slug="quatro-queijos", nome="Quatro Queijos", categoria=models.CategoriaPizza.especiais,
                         descricao="Mussarela, provolone, parmesão e gorgonzola", cor_hex="#D4A017",
                         preco_p=38, preco_m=49, preco_g=60),
            models.Pizza(slug="pepperoni", nome="Pepperoni", categoria=models.CategoriaPizza.tradicionais,
                         descricao="Molho de tomate, mussarela e pepperoni picante", cor_hex="#C1391F",
                         preco_p=37, preco_m=48, preco_g=59),
            models.Pizza(slug="toscana", nome="Toscana", categoria=models.CategoriaPizza.especiais,
                         descricao="Linguiça toscana, pimentão e cebola roxa", cor_hex="#9A2C17",
                         preco_p=38, preco_m=49, preco_g=60),
            models.Pizza(slug="vegetariana", nome="Vegetariana", categoria=models.CategoriaPizza.especiais,
                         descricao="Abobrinha, berinjela, tomate seco e rúcula", cor_hex="#4C6444",
                         preco_p=36, preco_m=47, preco_g=58),
            models.Pizza(slug="choco-morango", nome="Chocolate com Morango", categoria=models.CategoriaPizza.doces,
                         descricao="Chocolate ao leite derretido e morango fatiado", cor_hex="#5A3220",
                         preco_p=34, preco_m=44, preco_g=54),
            models.Pizza(slug="banana-canela", nome="Banana com Canela", categoria=models.CategoriaPizza.doces,
                         descricao="Banana, canela e leite condensado", cor_hex="#D4A017",
                         preco_p=32, preco_m=42, preco_g=52),
        ]
        db.add_all(pizzas)

    if db.query(models.Bebida).count() == 0:
        bebidas = [
            models.Bebida(nome="Coca-Cola 350ml", descricao="Lata gelada", preco=6),
            models.Bebida(nome="Guaraná 350ml", descricao="Lata gelada", preco=6),
            models.Bebida(nome="Suco Natural", descricao="Feito na hora", preco=8),
            models.Bebida(nome="Água Mineral", descricao="Com ou sem gás", preco=4),
        ]
        db.add_all(bebidas)

    if db.query(models.Ingrediente).count() == 0:
        ingredientes = [
            # Massas
            models.Ingrediente(nome="Tradicional", tipo=models.TipoIngrediente.massa, preco_adicional=0, cor_hex="#E9C989"),
            models.Ingrediente(nome="Fina", tipo=models.TipoIngrediente.massa, preco_adicional=0, cor_hex="#E9C989"),
            models.Ingrediente(nome="Integral", tipo=models.TipoIngrediente.massa, preco_adicional=2, cor_hex="#C9A876"),
            # Molhos
            models.Ingrediente(nome="Molho de tomate", tipo=models.TipoIngrediente.molho, preco_adicional=0, cor_hex="#B7371F"),
            models.Ingrediente(nome="Branco (alho e azeite)", tipo=models.TipoIngrediente.molho, preco_adicional=0, cor_hex="#EFE3C6"),
            models.Ingrediente(nome="Barbecue", tipo=models.TipoIngrediente.molho, preco_adicional=2, cor_hex="#5A2E14"),
            # Coberturas
            models.Ingrediente(nome="Mussarela", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#FFFBF3"),
            models.Ingrediente(nome="Calabresa", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#8B3A2B"),
            models.Ingrediente(nome="Frango", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#E8D9B5"),
            models.Ingrediente(nome="Presunto", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#E8A6A0"),
            models.Ingrediente(nome="Bacon", tipo=models.TipoIngrediente.topping, preco_adicional=4, cor_hex="#A85C3F"),
            models.Ingrediente(nome="Champignon", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#D9C9A8"),
            models.Ingrediente(nome="Cebola roxa", tipo=models.TipoIngrediente.topping, preco_adicional=2, cor_hex="#7A4B6B"),
            models.Ingrediente(nome="Pimentão", tipo=models.TipoIngrediente.topping, preco_adicional=2, cor_hex="#4C6444"),
            models.Ingrediente(nome="Azeitona", tipo=models.TipoIngrediente.topping, preco_adicional=2, cor_hex="#2B2B1E"),
            models.Ingrediente(nome="Milho", tipo=models.TipoIngrediente.topping, preco_adicional=2, cor_hex="#E8B923"),
            models.Ingrediente(nome="Catupiry", tipo=models.TipoIngrediente.topping, preco_adicional=4, cor_hex="#FFF6DC"),
            models.Ingrediente(nome="Gorgonzola", tipo=models.TipoIngrediente.topping, preco_adicional=4, cor_hex="#E9E2C9"),
            models.Ingrediente(nome="Rúcula", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#4C6444"),
            models.Ingrediente(nome="Tomate seco", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#7A2E1E"),
            models.Ingrediente(nome="Palmito", tipo=models.TipoIngrediente.topping, preco_adicional=3, cor_hex="#EDE4C8"),
        ]
        db.add_all(ingredientes)

    # Usuários padrão: funcionário da cozinha e dono (acesso gerencial).
    # Senhas podem vir do .env; troque-as antes de usar em produção.
    usuarios_padrao = [
        ("Cozinha BRASA", "cozinha@brasa.com", os.getenv("SENHA_PADRAO_COZINHA", "brasa123"), models.Cargo.cozinha),
        ("Dono BRASA", "dono@brasa.com", os.getenv("SENHA_PADRAO_DONO", "brasa123"), models.Cargo.admin),
    ]
    for nome, email, senha, cargo in usuarios_padrao:
        if not db.query(models.Usuario).filter(models.Usuario.email == email).first():
            db.add(models.Usuario(nome=nome, email=email, senha_hash=hash_senha(senha), cargo=cargo))

    db.commit()


def aguardar_banco(tentativas: int = 10, espera_segundos: float = 2.0):
    """Tenta conectar no MySQL algumas vezes antes de desistir.

    Útil em Docker: mesmo com o healthcheck do serviço 'db', o MySQL pode
    aceitar conexões de rede um instante antes de estar realmente pronto.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            with engine.connect():
                return
        except OperationalError:
            print(f"[startup] banco ainda não disponível (tentativa {tentativa}/{tentativas})...")
            time.sleep(espera_segundos)
    raise RuntimeError("Não foi possível conectar ao banco de dados após múltiplas tentativas")


@app.on_event("startup")
def on_startup():
    aguardar_banco()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()


@app.get("/")
def raiz():
    return {"status": "BRASA Pizzaria API no ar 🍕"}
