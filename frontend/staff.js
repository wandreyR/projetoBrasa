/* ============================================
   BRASA — Área da equipe (cozinha e gerencial)
   Sessão, login, chamadas autenticadas à API e utilitários.
   Chave localStorage: brasa_sessao = { token, nome, cargo }
   ============================================ */

const API_URL =
  window.BRASA_API_URL || `${location.protocol === 'https:' ? 'https:' : 'http:'}//${location.hostname || 'localhost'}:8002`;
const WS_URL = API_URL.replace(/^http/, 'ws');
const SESSAO_KEY = 'brasa_sessao';

const CARGO_LABEL = { admin: 'Dono / gerente', cozinha: 'Cozinha' };

/* ---------- Utilitários ---------- */

function formatPrice(value) {
  return (Number(value) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function escapeHTML(texto) {
  const div = document.createElement('div');
  div.textContent = texto == null ? '' : String(texto);
  return div.innerHTML;
}

// A API grava datas em UTC sem sufixo de fuso; sem o "Z" o navegador leria como hora local.
function parseDataApi(valor) {
  if (!valor) return null;
  const temFuso = /(Z|[+-]\d\d:\d\d)$/.test(valor);
  return new Date(temFuso ? valor : `${valor}Z`);
}

// Data local no formato YYYY-MM-DD (toISOString usaria UTC e erraria o dia à noite)
function dataISO(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function showToast(message, duracaoMs = 2600) {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    toast.setAttribute('role', 'status');
    toast.innerHTML = `<span class="dot-ok"></span><span class="toast-msg"></span>`;
    document.body.appendChild(toast);
  }
  toast.querySelector('.toast-msg').textContent = message;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), duracaoMs);
}

/* ---------- Sessão ---------- */

function getSessao() {
  try {
    return JSON.parse(localStorage.getItem(SESSAO_KEY)) || null;
  } catch (e) {
    return null;
  }
}

function salvarSessao(sessao) {
  localStorage.setItem(SESSAO_KEY, JSON.stringify(sessao));
}

function limparSessao() {
  localStorage.removeItem(SESSAO_KEY);
}

/* ---------- API autenticada ---------- */

class ErroSessao extends Error {}

function mensagemDeErroApi(corpo, status) {
  const detail = corpo && corpo.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((e) => String(e.msg || '').replace(/^Value error, /, '')).join(' · ');
  }
  return `Erro na requisição (HTTP ${status})`;
}

async function api(caminho, { method = 'GET', body } = {}) {
  const sessao = getSessao();
  const headers = {};
  if (sessao) headers.Authorization = `Bearer ${sessao.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let resp;
  try {
    resp = await fetch(`${API_URL}${caminho}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error('Sem conexão com o servidor. Verifique se o sistema está no ar.');
  }

  if (resp.status === 401) {
    limparSessao();
    abrirLogin('Sua sessão expirou. Entre novamente.');
    throw new ErroSessao('Sessão expirada');
  }
  if (resp.status === 204) return null;

  const corpo = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(mensagemDeErroApi(corpo, resp.status));
  return corpo;
}

/* ---------- Login ---------- */

let _configLogin = { cargos: ['admin', 'cozinha'], titulo: 'Entrar', onEntrar: () => {} };

function modalLoginHTML() {
  return `
    <div class="login-overlay" id="loginOverlay" hidden>
      <form class="login-card" id="loginForm" novalidate>
        <div class="brasa-logo"><span class="mark">BRA<em>SA</em></span></div>
        <p class="eyebrow">Área da equipe</p>
        <h2 id="loginTitulo">${escapeHTML(_configLogin.titulo)}</h2>
        <p class="login-msg" id="loginMsg" role="alert"></p>
        <label class="field">
          <span>E-mail</span>
          <input type="email" name="email" autocomplete="username" required>
        </label>
        <label class="field">
          <span>Senha</span>
          <input type="password" name="senha" autocomplete="current-password" required>
        </label>
        <button type="submit" class="btn btn-primary btn-block">Entrar</button>
        <a href="cardapio.html" class="login-voltar">← Voltar ao site</a>
      </form>
    </div>`;
}

function abrirLogin(mensagem = '') {
  const overlay = document.getElementById('loginOverlay');
  if (!overlay) return;
  document.getElementById('loginMsg').textContent = mensagem;
  overlay.hidden = false;
  document.body.classList.add('com-modal');
  setTimeout(() => overlay.querySelector('input[name="email"]').focus(), 50);
}

function fecharLogin() {
  const overlay = document.getElementById('loginOverlay');
  overlay.hidden = true;
  document.body.classList.remove('com-modal');
  overlay.querySelector('form').reset();
}

function cargoPermitido(cargo) {
  return _configLogin.cargos.includes(cargo);
}

function sair() {
  limparSessao();
  location.reload();
}

function renderUsuarioHeader(sessao) {
  const alvo = document.querySelector('[data-usuario]');
  if (alvo) {
    alvo.innerHTML = `
      <span class="usuario-nome">${escapeHTML(sessao.nome)}<small>${escapeHTML(CARGO_LABEL[sessao.cargo] || sessao.cargo)}</small></span>
      <button type="button" class="btn-sair" id="btnSair">Sair</button>`;
    document.getElementById('btnSair').addEventListener('click', sair);
  }
  // Link do gerencial só aparece para o dono
  document.querySelectorAll('[data-somente-admin]').forEach((el) => {
    el.hidden = sessao.cargo !== 'admin';
  });
}

/**
 * Garante que há um usuário logado com cargo permitido antes de iniciar a página.
 * cargos: lista de cargos aceitos; onEntrar(sessao): inicia a página.
 */
async function iniciarAreaEquipe({ cargos, titulo = 'Entrar', onEntrar }) {
  _configLogin = { cargos, titulo, onEntrar };
  document.body.insertAdjacentHTML('beforeend', modalLoginHTML());

  const form = document.getElementById('loginForm');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const botao = form.querySelector('[type="submit"]');
    botao.disabled = true;
    botao.textContent = 'Entrando…';
    const msg = document.getElementById('loginMsg');
    msg.textContent = '';

    try {
      const dados = new FormData(form);
      const resp = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: String(dados.get('email')).trim(), senha: dados.get('senha') }),
      });
      const corpo = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(mensagemDeErroApi(corpo, resp.status));
      if (!cargoPermitido(corpo.cargo)) {
        throw new Error('Seu usuário não tem acesso a esta área.');
      }
      const sessao = { token: corpo.access_token, nome: corpo.nome, cargo: corpo.cargo };
      salvarSessao(sessao);
      fecharLogin();
      renderUsuarioHeader(sessao);
      _configLogin.onEntrar(sessao);
    } catch (e) {
      msg.textContent = e.message === 'Failed to fetch' ? 'Sem conexão com o servidor.' : e.message;
    } finally {
      botao.disabled = false;
      botao.textContent = 'Entrar';
    }
  });

  const sessao = getSessao();
  if (!sessao) {
    abrirLogin();
    return;
  }

  // Confere se o token salvo ainda vale (e se o cargo continua o mesmo)
  try {
    const usuario = await api('/auth/me');
    if (!cargoPermitido(usuario.cargo)) {
      // Não apaga a sessão: outra aba (ex.: a cozinha) pode estar usando esse login.
      abrirLogin(`Você está logado como ${usuario.nome}. Entre com um usuário que tenha acesso a esta área.`);
      return;
    }
    const atualizada = { ...sessao, nome: usuario.nome, cargo: usuario.cargo };
    salvarSessao(atualizada);
    renderUsuarioHeader(atualizada);
    onEntrar(atualizada);
  } catch (e) {
    if (!(e instanceof ErroSessao)) abrirLogin(e.message);
  }
}

/* ---------- Tempo real (WebSocket compartilhado por cozinha e estoque) ---------- */

// Atualiza o indicador <span id="conexao"><span class="dot"></span><span id="conexaoTexto"></span></span>
function setConexao(estado, texto) {
  const el = document.getElementById('conexao');
  if (!el) return;
  el.dataset.estado = estado;
  document.getElementById('conexaoTexto').textContent = texto;
}

/**
 * Mantém uma conexão com /ws/cozinha: heartbeat, reconexão com espera crescente
 * e volta ao login se o token expirar (código 4401).
 * onAbrir(): chamado a cada (re)conexão — bom lugar para recarregar os dados.
 * onMensagem(msg): cada evento JSON recebido.
 */
function conectarTempoReal({ onAbrir, onMensagem }) {
  let socket = null;
  let tentativas = 0;
  let timerPing = null;
  let timerReconexao = null;

  function conectar() {
    const sessao = getSessao();
    if (!sessao) return;
    clearTimeout(timerReconexao);
    setConexao('conectando', 'Conectando…');

    const s = new WebSocket(`${WS_URL}/ws/cozinha?token=${encodeURIComponent(sessao.token)}`);
    socket = s;

    s.onopen = () => {
      if (s !== socket) return;
      tentativas = 0;
      setConexao('online', 'Ao vivo');
      clearInterval(timerPing);
      timerPing = setInterval(() => s.readyState === WebSocket.OPEN && s.send('ping'), 25000);
      if (onAbrir) onAbrir();
    };

    s.onmessage = (event) => {
      if (s !== socket || event.data === 'pong') return;
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      onMensagem(msg);
    };

    s.onclose = (event) => {
      if (s !== socket) return; // conexão antiga, substituída após novo login
      clearInterval(timerPing);
      if (event.code === 4401) {
        // token expirado: não adianta reconectar, precisa logar de novo
        limparSessao();
        setConexao('offline', 'Sessão expirada');
        abrirLogin('Sua sessão expirou. Entre novamente.');
        return;
      }
      tentativas += 1;
      const espera = Math.min(15000, 1000 * 2 ** (tentativas - 1));
      setConexao('offline', `Reconectando em ${Math.round(espera / 1000)}s…`);
      timerReconexao = setTimeout(conectar, espera);
    };
  }

  return {
    // (re)abre a conexão com o token atual — chamar após cada login
    iniciar() {
      const antigo = socket;
      conectar();
      if (antigo && antigo.readyState <= WebSocket.OPEN) antigo.close(1000);
    },
  };
}

/* ---------- Estoque: formatação compartilhada ---------- */

function formatarQtd(valor, unidade) {
  const casas = unidade === 'kg' ? 3 : 0;
  const n = Number(valor || 0).toLocaleString('pt-BR', { maximumFractionDigits: casas });
  return `${n} ${unidade}`;
}

const STATUS_ESTOQUE = {
  ok: { icone: '✓', texto: 'OK' },
  baixo: { icone: '⚠', texto: 'Abaixo do mínimo' },
  zerado: { icone: '✕', texto: 'Sem estoque' },
};
