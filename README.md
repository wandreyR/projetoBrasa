# BRASA Pizzaria

Sistema de pedidos de pizzaria: cardápio, montagem de pizza customizada, carrinho,
painel da cozinha com fila em tempo real (WebSocket) e área gerencial com
faturamento e despesas.

```
brasa-pizzaria/
├── docker-compose.yml
├── .env.example
├── backend/     → API FastAPI + SQLAlchemy + MySQL
└── frontend/    → HTML/CSS/JS estático (Nginx)
```

## Rodando tudo com Docker

### 1. Pré-requisitos
- Docker e Docker Compose instalados

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Os valores padrão já funcionam para rodar localmente. Só troque `JWT_SECRET`
antes de qualquer coisa que não seja teste local.

### 3. Subir os containers

```bash
docker compose up --build
```

Isso vai:
1. Subir o **MySQL** (`db`) com um volume persistente e aguardar ele ficar saudável
2. Subir o **backend FastAPI** (`backend`), que espera o banco, cria as tabelas e
   popula o cardápio automaticamente na primeira execução
3. Subir o **frontend** (`frontend`) servido via Nginx

### 4. Acessar

| Tela                        | URL                                   | Quem usa                    |
|-----------------------------|----------------------------------------|-----------------------------|
| Cardápio                    | http://localhost:8080/cardapio.html   | Clientes                    |
| Carrinho / finalizar pedido | http://localhost:8080/carrinho.html   | Clientes                    |
| Cozinha (Kanban ao vivo)    | http://localhost:8080/cozinha.html    | Funcionários e dono         |
| Gerencial                   | http://localhost:8080/gerencial.html  | Somente o dono              |
| Backend (Swagger)           | http://localhost:8002/docs            | Desenvolvimento             |
| MySQL (host)                | `localhost:3307` (usuário `root`)     | Desenvolvimento             |

**Usuários criados na primeira execução** (senhas definidas no `.env`, padrão `brasa123`):

| E-mail              | Cargo     | Acesso                   |
|---------------------|-----------|--------------------------|
| `cozinha@brasa.com` | `cozinha` | Tela da cozinha          |
| `dono@brasa.com`    | `admin`   | Cozinha + gerencial      |

⚠️ Troque essas senhas antes de usar fora do ambiente local.

> A porta do MySQL é exposta em **3307** no host (não 3306), para não colidir
> com um MySQL local que você já use em outro projeto, como o AutoForge.

### 5. Parar / limpar

```bash
docker compose down          # para os containers, mantém os dados do banco
docker compose down -v       # para os containers e apaga o volume do banco
```

### 6. Ver logs de um serviço específico

```bash
docker compose logs -f backend
```

## Rodando sem Docker (desenvolvimento local)

O `backend/README.md` explica como rodar a API sozinha com `venv` + MySQL local,
caso prefira não usar Docker no dia a dia.

## Fluxo do pedido

1. Cliente monta o carrinho e confirma em `carrinho.html` → `POST /pedidos`
   (o backend recalcula o preço das pizzas do cardápio e bebidas a partir do banco)
2. A cozinha recebe o pedido na hora via WebSocket (`/ws/cozinha?token=<jwt>`) com alerta sonoro
3. Kanban: **Novos → Em preparo → Prontos → Entregues** (entregue ao motoboy ou retirado pelo cliente)
4. O gerencial soma o faturamento dos pedidos não cancelados e compara com as despesas lançadas

## Próximos passos
- Conectar o cardápio e o "Monte sua pizza" às rotas reais do backend (hoje ainda
  usam dados fixos em JavaScript)
- Levar para o banco os preços base da pizza montada (hoje o preço dela ainda vem do front)
- Adicionar um proxy reverso (Nginx ou Traefik) na frente de frontend + backend,
  para que o frontend chame `/api/...` sem se preocupar com host/porta do backend
