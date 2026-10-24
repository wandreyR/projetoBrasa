/* ============================================
   BRASA — Máscaras de campos
   ============================================ */

// "62999990000" → "(62) 99999-0000"; 10 dígitos (fixo) → "(62) 3333-4444". Máximo de 11 dígitos.
function formatarTelefoneDigitado(valor) {
  let d = String(valor || '').replace(/\D/g, '');
  if (d.length > 11 && d.startsWith('55')) d = d.slice(2); // colou com +55 na frente
  d = d.slice(0, 11);
  if (!d) return '';
  if (d.length <= 2) return `(${d}`;
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
}

/**
 * Aplica a máscara num <input>: aceita só números, limita a 11 dígitos e
 * marca o campo como inválido (mensagem do navegador) se faltar dígito.
 * obrigatorio=false: campo vazio é aceito (ex.: telefone do entregador).
 */
function aplicarMascaraTelefone(input, { obrigatorio = true } = {}) {
  if (!input || input.dataset.mascara) return;
  input.dataset.mascara = 'telefone';
  input.setAttribute('inputmode', 'numeric');
  input.setAttribute('autocomplete', input.getAttribute('autocomplete') || 'tel');
  input.placeholder = input.placeholder || '(62) 99999-0000';

  const validar = () => {
    const digitos = input.value.replace(/\D/g, '').length;
    const vazioPermitido = !obrigatorio && digitos === 0;
    input.setCustomValidity(vazioPermitido || digitos >= 10 ? '' : 'Informe o DDD + número (10 ou 11 dígitos)');
  };

  input.addEventListener('input', () => {
    input.value = formatarTelefoneDigitado(input.value);
    validar();
  });
  // teclas que não são número nem de edição não chegam a aparecer
  input.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.key.length > 1) return; // Backspace, setas, Tab, colar…
    if (!/\d/.test(e.key)) e.preventDefault();
  });

  input.value = formatarTelefoneDigitado(input.value);
  validar();
}
