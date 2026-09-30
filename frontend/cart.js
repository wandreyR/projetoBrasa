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

const TAXA_ENTREGA = 6; // mesmo valor de TAXA_ENTREGA_PADRAO no backend
const TIMEOUT_PEDIDO_MS = 15000;
const ULTIMO_PEDIDO_KEY = 'brasa_ultimo_pedido';

// O cardápio salva bebidas como tipo 'cardapio' sem tamanho; a API diferencia.
function tipoItemApi(item) {
  if (item.tipo === 'custom') return 'custom';
  return item.tamanho ? 'cardapio' : 'bebida';
}

function montarPayloadPedido(cliente) {
  return {
    cliente_nome: cliente.nome,
    cliente_telefone: cliente.telefone,
    tipo_entrega: cliente.tipoEntrega,
    endereco_entrega: cliente.tipoEntrega === 'delivery' ? cliente.endereco : null,
    observacoes: cliente.observacoes || null,
    itens: getCart().map((item) => {
      const tipo = tipoItemApi(item);
      return {
        tipo,
        // pizza do cardápio → slug; bebida → nome. O backend usa isso para buscar o preço oficial.
        ref: tipo === 'cardapio' ? String(item.id) : tipo === 'bebida' ? item.nome : null,
        nome: item.nome,
        tamanho: item.tamanho || null,
        preco_unitario: item.precoUnit,
        quantidade: item.qtd,
        detalhes: item.detalhes || null,
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
 * form: <form> com campos name="nome", "telefone", "tipo_entrega", "endereco", "observacoes"
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
      observacoes: String(dados.get('observacoes') || '').trim(),
    });

    enviando = true;
    if (botao) {
      botao.disabled = true;
      botao.textContent = 'Enviando pedido…';
    }

    try {
      const pedido = await enviarPedido(payload);
      localStorage.setItem(ULTIMO_PEDIDO_KEY, JSON.stringify({ id: pedido.id, total: pedido.total }));
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

document.addEventListener('DOMContentLoaded', renderCartBadge);
