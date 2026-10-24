/* ============================================
   BRASA — Estado do carrinho (compartilhado)
   Chave localStorage: carrinho_pizzaria
   Item: { id, nome, tamanho, precoUnit, qtd, detalhes }
   ============================================ */

const CART_KEY = 'carrinho_pizzaria';

function getCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error('Erro ao ler carrinho:', e);
    return [];
  }
}

function saveCart(cart) {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
  renderCartBadge();
}

function addToCart(item) {
  const cart = getCart();
  // Combina apenas se for item idêntico de cardápio (mesmo id + tamanho, sem customização)
  const existing = cart.find(
    (i) => i.id === item.id && i.tamanho === item.tamanho && i.tipo === item.tipo && !item.customId
  );
  if (existing && !item.customId) {
    existing.qtd += item.qtd;
  } else {
    cart.push({ ...item, customId: item.customId || `${item.id}-${Date.now()}` });
  }
  saveCart(cart);
}

function removeFromCart(customId) {
  const cart = getCart().filter((i) => i.customId !== customId);
  saveCart(cart);
}

function updateQty(customId, delta) {
  const cart = getCart();
  const item = cart.find((i) => i.customId === customId);
  if (!item) return;
  item.qtd += delta;
  if (item.qtd <= 0) {
    removeFromCart(customId);
    return;
  }
  saveCart(cart);
}

function getCartCount() {
  return getCart().reduce((sum, i) => sum + i.qtd, 0);
}

function getCartTotal() {
  return getCart().reduce((sum, i) => sum + i.precoUnit * i.qtd, 0);
}

function formatPrice(value) {
  return `R$ ${value.toFixed(2).replace('.', ',')}`;
}

function renderCartBadge() {
  const badge = document.querySelector('[data-cart-badge]');
  if (!badge) return;
  const count = getCartCount();
  badge.textContent = count;
  badge.style.display = count > 0 ? 'flex' : 'none';
}

function showToast(message, duracaoMs = 2200) {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<span class="dot-ok"></span><span class="toast-msg"></span>`;
    document.body.appendChild(toast);
  }
  toast.querySelector('.toast-msg').textContent = message;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), duracaoMs);
}

/* ============================================
   Envio do pedido para a API (POST /pedidos)
   ============================================ */

// Pode ser sobrescrita definindo window.BRASA_API_URL antes de carregar este script
// (ex.: quando houver proxy reverso servindo a API em /api).
const API_URL =
  window.BRASA_API_URL || `${location.protocol === 'https:' ? 'https:' : 'http:'}//${location.hostname || 'localhost'}:8002`;

const TIMEOUT_PEDIDO_MS = 15000;
const ULTIMO_PEDIDO_KEY = 'brasa_ultimo_pedido';
const HORAS_LINK_ACOMPANHAR = 12; // por quanto tempo o topo do site mostra "Seu pedido #N"

// GET simples na API pública (cardápio, loja, bairros…)
async function apiPublica(caminho) {
  const resp = await fetch(`${API_URL}${caminho}`);
  if (!resp.ok) throw new Error(`Erro ao carregar ${caminho} (HTTP ${resp.status})`);
  return resp.json();
}

/* ---------- Loja aberta / fechada ---------- */

let statusLoja = { aberto: true, mensagem: '' };

// Mostra uma faixa no topo da página quando a pizzaria está fechada ou pausada
async function carregarStatusLoja() {
  try {
    statusLoja = await apiPublica('/cardapio/loja');
  } catch (e) {
    return statusLoja; // sem API: não bloqueia nada aqui; o pedido é validado no servidor
  }
  let faixa = document.querySelector('.aviso-loja');
  if (!statusLoja.aberto) {
    if (!faixa) {
      faixa = document.createElement('div');
      faixa.className = 'aviso-loja';
      faixa.setAttribute('role', 'status');
      document.querySelector('.brasa-header').insertAdjacentElement('afterend', faixa);
    }
    faixa.innerHTML = `<span aria-hidden="true">🕒</span> ${statusLoja.mensagem} Você pode montar o carrinho e pedir quando abrirmos.`;
  } else if (faixa) {
    faixa.remove();
  }
  document.dispatchEvent(new CustomEvent('brasa:loja', { detail: statusLoja }));
  return statusLoja;
}

/* ---------- Último pedido (link de acompanhamento no topo) ---------- */

function getUltimoPedido() {
  try {
    const p = JSON.parse(localStorage.getItem(ULTIMO_PEDIDO_KEY));
    if (!p || !p.codigo) return null;
    if (Date.now() - (p.quando || 0) > HORAS_LINK_ACOMPANHAR * 3600 * 1000) return null;
    return p;
  } catch (e) {
    return null;
  }
}

function linkAcompanhar(codigo) {
  return `acompanhar.html?c=${encodeURIComponent(codigo)}`;
}

function renderLinkUltimoPedido() {
  const p = getUltimoPedido();
  const carrinho = document.querySelector('.cart-link');
  if (!p || !carrinho || document.querySelector('.acompanhar-link')) return;
  carrinho.insertAdjacentHTML('beforebegin',
    `<a class="acompanhar-link" href="${linkAcompanhar(p.codigo)}">Pedido #${p.id}</a>`);
}

// O cardápio salva bebidas como tipo 'cardapio' sem tamanho; a API diferencia.
function tipoItemApi(item) {
  if (item.tipo === 'custom') return 'custom';
  return item.tamanho ? 'cardapio' : 'bebida';
}

// Pizza montada: massa, molho e coberturas escolhidos. Itens adicionados antes desta
// versão só têm o texto "Massa · Molho · a, b" em detalhes — nesse caso, extrai de lá.
function ingredientesDaPizza(item) {
  if (Array.isArray(item.ingredientes)) return item.ingredientes;
  const partes = String(item.detalhes || '').split(' · ');
  if (partes.length < 3) return null;
  const coberturas = partes.slice(2).join(' · ');
  return [partes[0], partes[1], ...(coberturas === 'sem ingredientes extras' ? [] : coberturas.split(', '))];
}

function montarPayloadPedido(cliente) {
  return {
    cliente_nome: cliente.nome,
    cliente_telefone: cliente.telefone,
    tipo_entrega: cliente.tipoEntrega,
    endereco_entrega: cliente.tipoEntrega === 'delivery' ? cliente.endereco : null,
    bairro_id: cliente.tipoEntrega === 'delivery' ? Number(cliente.bairroId) || null : null,
    forma_pagamento: cliente.formaPagamento,
    troco_para: cliente.formaPagamento === 'dinheiro' && cliente.trocoPara ? Number(cliente.trocoPara) : null,
    observacoes: cliente.observacoes || null,
    itens: getCart().map((item) => {
      const tipo = tipoItemApi(item);
      return {
        tipo,
        // slug da pizza/bebida: o backend busca o preço oficial (o preço do navegador não é enviado)
        ref: tipo === 'custom' ? null : String(item.id),
        nome: item.nome,
        tamanho: item.tamanho || null,
        quantidade: item.qtd,
        detalhes: item.detalhes || null,
        ingredientes: tipo === 'custom' ? ingredientesDaPizza(item) : null,
      };
    }),
  };
}

// Converte o erro do FastAPI (string ou lista de erros de validação) em texto legível
function mensagemDeErroApi(corpo, status) {
  const detail = corpo && corpo.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((e) => String(e.msg || '').replace(/^Value error, /, '')).join(' · ');
  }
  return `Erro ao enviar pedido (HTTP ${status})`;
}

async function enviarPedido(payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_PEDIDO_MS);
  let resp;
  try {
    resp = await fetch(`${API_URL}/pedidos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (e) {
    throw new Error(
      e.name === 'AbortError'
        ? 'O servidor demorou para responder. Verifique sua conexão e tente novamente.'
        : 'Não foi possível conectar ao servidor da pizzaria. Tente novamente em instantes.'
    );
  } finally {
    clearTimeout(timer);
  }

  const corpo = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(mensagemDeErroApi(corpo, resp.status));
  return corpo;
}

/**
 * Intercepta o submit do formulário de checkout ("Confirmar pedido"),
 * envia o carrinho para POST /pedidos e limpa o carrinho em caso de sucesso.
 *
 * form: <form> com campos name="nome", "telefone", "tipo_entrega", "endereco", "bairro_id",
 *       "forma_pagamento", "troco_para", "observacoes"
 * onSuccess(pedido): chamado com a resposta da API (PedidoOut)
 */
function initCheckout(form, { onSuccess } = {}) {
  if (!form) return;
  const botao = form.querySelector('[type="submit"]');
  const textoOriginal = botao ? botao.textContent : '';
  let enviando = false;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (enviando) return; // evita pedido duplicado em duplo clique

    if (getCart().length === 0) {
      showToast('Seu carrinho está vazio');
      return;
    }
    if (!form.reportValidity()) return;

    const dados = new FormData(form);
    const payload = montarPayloadPedido({
      nome: String(dados.get('nome') || '').trim(),
      telefone: String(dados.get('telefone') || '').trim(),
      tipoEntrega: dados.get('tipo_entrega'),
      endereco: String(dados.get('endereco') || '').trim(),
      bairroId: dados.get('bairro_id'),
      formaPagamento: dados.get('forma_pagamento'),
      trocoPara: String(dados.get('troco_para') || '').replace(',', '.'),
      observacoes: String(dados.get('observacoes') || '').trim(),
    });

    enviando = true;
    if (botao) {
      botao.disabled = true;
      botao.textContent = 'Enviando pedido…';
    }

    try {
      const pedido = await enviarPedido(payload);
      localStorage.setItem(ULTIMO_PEDIDO_KEY, JSON.stringify({
        id: pedido.id, total: pedido.total, codigo: pedido.codigo_acompanhamento, quando: Date.now(),
      }));
      saveCart([]);
      if (onSuccess) onSuccess(pedido);
    } catch (e) {
      showToast(e.message, 5000);
    } finally {
      enviando = false;
      if (botao) {
        botao.disabled = false;
        botao.textContent = textoOriginal;
      }
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  renderCartBadge();
  renderLinkUltimoPedido();
});

/* ============================================
   Pix: QR Code, "copia e cola" e envio do comprovante
   (usado na confirmação do pedido e na página de acompanhamento)
   ============================================ */

const LIMITE_COMPROVANTE = 5 * 1024 * 1024;
const TIPOS_COMPROVANTE = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];

function escaparPix(texto) {
  const div = document.createElement('div');
  div.textContent = texto == null ? '' : String(texto);
  return div.innerHTML;
}

async function copiarTexto(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch (e) {
    // navegador sem permissão de área de transferência: seleciona para copiar à mão
    return false;
  }
}

/**
 * alvo: elemento onde o painel é desenhado; codigo: código de acompanhamento do pedido
 * estado: { comprovanteEnviado, pago } — para mostrar "já enviado"/"pagamento confirmado"
 */
async function renderPainelPix(alvo, codigo, estado = {}) {
  if (estado.pago) {
    alvo.innerHTML = '<div class="painel-pix pago"><b>✓ Pagamento Pix confirmado pela pizzaria.</b></div>';
    return;
  }
  alvo.innerHTML = '<div class="painel-pix"><p>Carregando o Pix…</p></div>';
  let pix;
  try {
    pix = await apiPublica(`/pedidos/acompanhar/${encodeURIComponent(codigo)}/pix`);
  } catch (e) {
    alvo.innerHTML = '<div class="painel-pix"><p>Não foi possível carregar o Pix. Fale com a pizzaria pelo telefone.</p></div>';
    return;
  }
  const svg = pix.qr_svg.replace(/<\?xml[^>]*>/, ''); // SVG gerado pelo nosso servidor
  alvo.innerHTML = `
    <div class="painel-pix">
      <h3>Pague com Pix: ${formatPrice(pix.valor)}</h3>
      <p class="pix-passos">Abra o app do seu banco, escolha <b>Pix → Ler QR Code</b> ou <b>Pix copia e cola</b>.</p>
      <div class="pix-grade">
        <div class="pix-qr" role="img" aria-label="QR Code do Pix">${svg}</div>
        <div class="pix-dados">
          <label class="pix-rotulo" for="pixCopia">Pix copia e cola</label>
          <div class="pix-copia">
            <input id="pixCopia" type="text" readonly value="${escaparPix(pix.copia_e_cola)}">
            <button type="button" class="btn btn-dark" data-copiar="${escaparPix(pix.copia_e_cola)}">Copiar</button>
          </div>
          <p class="pix-chave">Chave: <b>${escaparPix(pix.chave)}</b>
            <button type="button" class="link-copiar" data-copiar="${escaparPix(pix.chave)}">copiar chave</button><br>
            Favorecido: ${escaparPix(pix.nome)}</p>
        </div>
      </div>
      <div class="pix-comprovante">
        <p class="pix-rotulo">Já pagou? Envie o comprovante para a pizzaria:</p>
        <label class="btn btn-primary botao-arquivo">
          📎 ${estado.comprovanteEnviado ? 'Enviar outro comprovante' : 'Enviar comprovante'}
          <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" hidden>
        </label>
        <span class="pix-status" role="status">${estado.comprovanteEnviado ? '✓ Comprovante recebido — a pizzaria vai conferir.' : 'Foto ou PDF, até 5 MB.'}</span>
      </div>
    </div>`;

  alvo.querySelectorAll('[data-copiar]').forEach(btn => btn.addEventListener('click', async () => {
    const copiou = await copiarTexto(btn.dataset.copiar);
    if (!copiou) alvo.querySelector('#pixCopia').select();
    showToast(copiou ? 'Copiado! Cole no app do banco.' : 'Selecionado: use Ctrl+C para copiar');
  }));

  const campo = alvo.querySelector('input[type="file"]');
  const status = alvo.querySelector('.pix-status');
  campo.addEventListener('change', async () => {
    const arquivo = campo.files[0];
    campo.value = '';
    if (!arquivo) return;
    if (!TIPOS_COMPROVANTE.includes(arquivo.type)) {
      status.textContent = 'Envie uma foto (JPG, PNG ou WEBP) ou um PDF.';
      return;
    }
    if (arquivo.size > LIMITE_COMPROVANTE) {
      status.textContent = 'Arquivo muito grande: o limite é 5 MB.';
      return;
    }
    status.textContent = 'Enviando…';
    const dados = new FormData();
    dados.append('arquivo', arquivo);
    try {
      const resp = await fetch(`${API_URL}/pedidos/acompanhar/${encodeURIComponent(codigo)}/comprovante`, { method: 'POST', body: dados });
      const corpo = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(mensagemDeErroApi(corpo, resp.status));
      status.textContent = '✓ Comprovante recebido — a pizzaria vai conferir.';
      alvo.querySelector('.botao-arquivo').firstChild.textContent = '📎 Enviar outro comprovante ';
      showToast('Comprovante enviado para a pizzaria');
    } catch (e) {
      status.textContent = e.message === 'Failed to fetch' ? 'Sem conexão. Tente de novo.' : e.message;
    }
  });
}
