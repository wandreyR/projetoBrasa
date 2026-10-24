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
| Acompanhar pedido           | link mostrado após confirmar          | Clientes                    |
| Cozinha (Kanban ao vivo)    | http://localhost:8080/cozinha.html    | Funcionários e dono         |
| Estoque                     | http://localhost:8080/estoque.html    | Funcionários e dono         |
| Gerencial                   | http://localhost:8080/gerencial.html  | Somente o dono              |
| Configurações               | http://localhost:8080/configuracoes.html | Somente o dono (cardápio, preços, bairros, entregadores, horário) |
| Backend (Swagger)           | http://localhost:8002/docs            | Desenvolvimento             |
| MySQL (host)                | `localhost:3307` (usuário `root`)     | Desenvolvimento             |

**Usuários criados na primeira execução** (senhas definidas no `.env`, padrão `brasa123`):

| E-mail              | Cargo     | Acesso                   |
|---------------------|-----------|--------------------------|
| `cozinha@brasa.com` | `cozinha` | Tela da cozinha          |
| `dono@brasa.com`    | `admin`   | Cozinha + gerencial + configurações |

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

1. O cliente monta o carrinho. Cardápio, tamanhos e adicionais vêm do banco (o dono muda em
   **Configurações**); no "Monte a sua" a pizza é montada na tela: a massa abre, o molho espalha e
   cada ingrediente cai em pedaços — o botão **▶ Ver a montagem** repete tudo e termina no forno
2. No carrinho escolhe **entrega** (bairro → taxa) ou **retirada** e a **forma de pagamento**
   (Pix, crédito, débito ou dinheiro com troco). O pagamento é feito na entrega/retirada
3. `POST /pedidos`: o backend **recalcula todos os preços** (inclusive a pizza montada), confere o
   **horário de funcionamento**/pausa e o **estoque**, e devolve um **link de acompanhamento**
4. A cozinha recebe o pedido na hora (WebSocket) com **alarme que repete** até alguém ver,
   opcionalmente **imprime a comanda** (80 mm) e o pedido anda pelo Kanban:
   **Novos → Em preparo → Prontos → Saiu p/ entrega (com o entregador) → Finalizados**
5. O cliente acompanha as etapas pelo link (atualiza sozinho). A cozinha marca **pago** quando recebe
6. O gerencial mostra faturamento, despesas, **formas de pagamento**, **valor a receber** e
   **entregas por entregador** (para acertar com os motoboys)

A cozinha pode **pausar os pedidos do site** quando estiver sobrecarregada.

## Banco de dados e migrações (Alembic)

O esquema do banco é versionado em `backend/migrations/`. **O backend aplica as migrações
sozinho ao iniciar** — não é preciso rodar nada no Docker. Um banco criado antes do Alembic é
reconhecido e atualizado sem perder dados.

Ao mudar um model (`backend/app/models.py`):

```bash
cd backend
alembic revision --autogenerate -m "o que mudou"   # gera a migração; revise o arquivo gerado
alembic upgrade head                               # aplica (ou reinicie o backend)
```

## Testes

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

Cada arquivo de teste roda num banco SQLite em memória criado pelas mesmas migrações de produção.

## Backup do banco

O serviço `backup` do Docker Compose faz um dump do MySQL **ao subir e todo dia às 04:00**,
na pasta `backups/` do projeto (fora do Git), e apaga os com mais de 14 dias.

```bash
docker compose exec backup /backup.sh                                    # backup agora
docker compose exec backup /restaurar.sh brasa_2026-10-23_0400.sql.gz    # restaura (apaga os dados atuais!)
```

Os **comprovantes do Pix** enviados pelos clientes ficam no volume `brasa_comprovantes` e entram no
backup como `comprovantes_<data>.tar.gz`.

> No **Git Bash** (Windows), coloque `MSYS_NO_PATHCONV=1` antes do comando
> (`MSYS_NO_PATHCONV=1 docker compose exec backup /backup.sh`); no PowerShell funciona direto.

⚠️ A pasta `backups/` fica no mesmo computador: copie os arquivos para a nuvem ou um HD externo.

## Estoque

- Itens em **unidades** (bebidas, caixas) ou **kg** (farinha, queijos, molhos)
- Alerta quando o saldo fica **abaixo do mínimo** — padrão **10 un** e **10 kg**, ajustável por item.
  A cozinha vê o aviso em tempo real no topo do Kanban
- **Baixa automática:**
  - bebidas ligadas a um item de estoque saem a cada pedido (1 un por bebida vendida)
  - pizza montada pelo cliente baixa os kg de massa, molho e coberturas conforme a
    *Receita da pizza montada* (kg por tamanho P/M/G, editável na tela de estoque)
- **Baixa manual:** os demais produtos em kg (pizzas do cardápio) são lançados pelos
  funcionários com *Entrada*, *Saída* ou *Contagem* (corrige o saldo após contar)
- **Venda sem estoque é proibida:** bebida zerada aparece como *Esgotado* no cardápio, ingrediente
  sem saldo para o tamanho escolhido fica desabilitado no "Monte a sua", e a API recusa o pedido
  (HTTP 409) se faltar qualquer item — as linhas do estoque são travadas durante o pedido para
  dois clientes não comprarem a última unidade ao mesmo tempo
- Saída manual maior que o saldo é recusada (use *Contagem* para corrigir o saldo)
- Pedido cancelado devolve ao estoque o que foi baixado automaticamente; reabrir exige saldo
- Todo movimento fica no histórico (quem fez, quando, qual pedido)

## Fotos

- `frontend/img/pizzas/<id>.jpg`, `frontend/img/bebidas/<id>.jpg` e `frontend/img/ingredientes/<id>.jpg`
  (o `<id>` é o mesmo usado no cardápio / "Monte a sua"; ex.: `pizzas/margherita.jpg`)
- Quatro Queijos, Calabresa, Frango com Catupiry e Portuguesa são fotos do acervo da pizzaria
  (originais em `img/`); as demais vêm do Wikimedia Commons sob licenças livres
- Os créditos (autor e licença, exigidos pelas licenças CC BY/BY-SA) ficam em
  `frontend/img/creditos.json` e aparecem na página `creditos.html`
- Para trocar uma foto: salve um JPG quadrado (~600px) com o mesmo nome, atualize o
  `creditos.json` e rode `docker compose up --build -d frontend`

## Próximos passos
- Trocar as senhas padrão e criar uma tela para cadastrar/desativar funcionários
- Pagamento online (Pix com QR Code / cartão) — exige conta num provedor de pagamento
- Publicar na internet com HTTPS e um proxy reverso servindo frontend + backend (`/api/...`)
- Copiar os backups automaticamente para a nuvem
