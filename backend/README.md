# BRASA Pizzaria — Backend

API em FastAPI + SQLAlchemy + MySQL para o sistema de pedidos da pizzaria.

## 1. Criar o banco de dados

No MySQL local:

```sql
CREATE DATABASE brasa_pizzaria_db;
```

## 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` com o usuário/senha do seu MySQL local

## 3. Instalar dependências

Recomendado usar um ambiente virtual:

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Rodar o servidor

```bash
uvicorn app.main:app --reload --port 8002
```

Na primeira execução, a API cria as tabelas automaticamente e popula:
- 10 pizzas do cardápio
- 4 bebidas
- Massas, molhos e coberturas para o "Monte sua pizza"
- Dois usuários padrão (senhas em `SENHA_PADRAO_COZINHA` / `SENHA_PADRAO_DONO`, padrão `brasa123`):
  - **Cozinha:** `cozinha@brasa.com` — acesso à fila da cozinha
  - **Dono:** `dono@brasa.com` — acesso à cozinha e ao gerencial

  ⚠️ Troque essas senhas antes de usar em produção.

## 5. Documentação interativa

Com o servidor rodando, acesse:
- Swagger UI: http://localhost:8002/docs
- ReDoc: http://localhost:8002/redoc

## Rotas principais

| Método | Rota                                  | Autenticação | Descrição                                   |
|--------|----------------------------------------|--------------|----------------------------------------------|
| GET    | `/cardapio/pizzas`                    | não          | Lista pizzas (filtro opcional `?categoria=`) |
| GET    | `/cardapio/bebidas`                   | não          | Lista bebidas                                |
| GET    | `/cardapio/ingredientes`              | não          | Lista massas/molhos/coberturas               |
| POST   | `/pedidos`                            | não          | Cria um pedido (cliente)                     |
| GET    | `/pedidos/{id}`                       | não          | Consulta status de um pedido                 |
| POST   | `/auth/login`                         | não          | Login da cozinha/admin, retorna JWT          |
| GET    | `/cozinha/pedidos`                    | sim          | Lista a fila de pedidos                      |
| PATCH  | `/cozinha/pedidos/{id}/status`        | sim          | Atualiza status (pendente → em_preparo → …)  |
| WS     | `/ws/cozinha?token=<jwt>`             | sim          | Eventos em tempo real da cozinha             |
| GET    | `/estoque/itens`                      | sim          | Itens com saldo e status (ok/baixo/zerado)   |
| GET    | `/estoque/alertas`                    | sim          | Itens abaixo do mínimo                       |
| POST   | `/estoque/itens`                      | sim          | Cadastra item (mínimo padrão 20 un / 10 kg)  |
| PUT    | `/estoque/itens/{id}`                 | sim          | Edita nome, unidade, mínimo, bebida ligada   |
| DELETE | `/estoque/itens/{id}`                 | dono         | Exclui item (mantém histórico)               |
| POST   | `/estoque/itens/{id}/movimentar`      | sim          | Entrada, saída ou contagem                   |
| GET    | `/estoque/movimentacoes`              | sim          | Histórico de movimentações                   |
| GET/PUT| `/estoque/consumo[/{ingrediente_id}]` | sim          | Receita da pizza montada (kg por tamanho)    |
| GET    | `/gerencial/resumo?inicio=&fim=`      | dono         | Faturamento, despesas, lucro, top itens      |
| GET    | `/gerencial/despesas`                 | dono         | Lista despesas do período                    |
| POST   | `/gerencial/despesas`                 | dono         | Lança uma despesa                            |
| PUT    | `/gerencial/despesas/{id}`            | dono         | Edita uma despesa                            |
| DELETE | `/gerencial/despesas/{id}`            | dono         | Exclui uma despesa                           |

## WebSocket da cozinha

- Conectar com `ws://localhost:8002/ws/cozinha?token=<jwt>` (o token vai na URL porque o navegador não envia header em WebSocket)
- Fechamento com código `4401` = token inválido/expirado → fazer login de novo
- Enviar `"ping"` periodicamente; o servidor responde `"pong"`
- Eventos: `{"evento": "novo_pedido" | "status_atualizado", "pedido": {...}}`
