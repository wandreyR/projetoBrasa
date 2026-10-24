/* ============================================
   BRASA — Simulação da montagem da pizza
   A massa abre, o molho espalha e cada cobertura cai em pedaços
   sobre a pizza. Usado pela página "Monte a sua".
   ============================================ */

// Como cada cobertura aparece na pizza (tamanhos em % do diâmetro).
// Coberturas novas cadastradas no banco usam o formato "disco" com a cor do banco.
const PECAS_COBERTURA = {
  mussarela: { forma: 'queijo', n: 7, tam: [17, 25], cores: ['#FFF4D6', '#F7DFA0'] },
  calabresa: { forma: 'disco', n: 7, tam: [9, 11], cores: ['#B04A33', '#8B3426'] },
  frango: { forma: 'fiapo', n: 11, tam: [7, 10], cores: ['#EADBB8', '#D4BC8E'] },
  presunto: { forma: 'quadrado', n: 6, tam: [9, 12], cores: ['#EDB0A8', '#E39A91'] },
  bacon: { forma: 'tira', n: 6, tam: [13, 17], cores: ['#A9543A', '#C9785A'] },
  champignon: { forma: 'cogumelo', n: 7, tam: [7, 9], cores: ['#DCCBA8', '#B9A27A'] },
  cebola: { forma: 'anel', n: 7, tam: [8, 11], cores: ['#8A4F79', '#B07AA1'] },
  pimentao: { forma: 'arco', n: 7, tam: [9, 12], cores: ['#3F7A31', '#5C9A45'] },
  azeitona: { forma: 'azeitona', n: 8, tam: [5, 6.5], cores: ['#24241A', '#3B3B2C'] },
  milho: { forma: 'grao', n: 18, tam: [2.6, 3.4], cores: ['#F2C230', '#E2A912'] },
  catupiry: { forma: 'gota', n: 6, tam: [8, 11], cores: ['#FFFAEB', '#F1E4C2'] },
  gorgonzola: { forma: 'gorgonzola', n: 7, tam: [6, 8.5], cores: ['#F1EBD8', '#DCD3B6'] },
  rucula: { forma: 'folha', n: 9, tam: [10, 13], cores: ['#4E8A3A', '#2F6626'] },
  'tomate-seco': { forma: 'pedaco', n: 7, tam: [7, 9], cores: ['#9A2E1D', '#6E1E12'] },
  palmito: { forma: 'palmito', n: 6, tam: [7, 9], cores: ['#F4ECD3', '#E2D3AA'] },
};

const CORES_MASSA = { tradicional: '#E9C989', fina: '#F0D9A6', integral: '#C49A6C' };
const CORES_MOLHO = { tomate: '#B7371F', branco: '#F1E6CB', barbecue: '#5A2E14' };

// Gerador pseudoaleatório com semente: a mesma cobertura cai sempre no mesmo lugar
function geradorSemente(texto) {
  let h = 1779033703 ^ texto.length;
  for (let i = 0; i < texto.length; i++) {
    h = Math.imul(h ^ texto.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));
const SEM_ANIMACAO = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

class MontagemPizza {
  /**
   * palco: elemento .palco-pizza com .pizza-montagem, .camada-massa, .camada-molho e .camada-pecas
   * narrar(texto): mostra o que está acontecendo ("Espalhando o molho…")
   */
  constructor(palco, { narrar } = {}) {
    this.palco = palco;
    this.pizza = palco.querySelector('.pizza-montagem');
    this.massa = palco.querySelector('.camada-massa');
    this.molho = palco.querySelector('.camada-molho');
    this.pecas = palco.querySelector('.camada-pecas');
    this.narrar = narrar || (() => {});
    this.grupos = new Map(); // "slug#porção" → elemento com os pedaços
    this.reproduzindo = false;
  }

  setTamanho(codigo) {
    this.pizza.dataset.tamanho = codigo;
  }

  setMassa(slug, nome, cor, animar = true) {
    this.pizza.dataset.massa = slug;
    this.massa.style.setProperty('--cor-massa', CORES_MASSA[slug] || cor || CORES_MASSA.tradicional);
    if (animar) {
      this._reiniciarAnimacao(this.massa, 'abrindo');
      this._farinha();
      this.narrar(`Abrindo a massa ${nome.toLowerCase()}…`);
    }
  }

  setMolho(slug, nome, cor, animar = true) {
    this.molho.style.setProperty('--cor-molho', CORES_MOLHO[slug] || cor || CORES_MOLHO.tomate);
    if (animar) {
      this._reiniciarAnimacao(this.molho, 'espalhando');
      this.narrar(`Espalhando o ${nome.toLowerCase().startsWith('molho') ? nome.toLowerCase() : `molho ${nome.toLowerCase()}`}…`);
    }
  }

  /**
   * porcoes: [{ slug, nome, cor, porcao }] — uma entrada por porção (bacon 2× = 2 entradas).
   * Só anima o que mudou: porções novas caem, porções retiradas saem.
   */
  setCoberturas(porcoes, animar = true) {
    const chaves = new Set(porcoes.map((p) => `${p.slug}#${p.porcao}`));
    let novas = 0;

    this.grupos.forEach((grupo, chave) => {
      if (chaves.has(chave)) return;
      this.grupos.delete(chave);
      if (animar && !SEM_ANIMACAO) {
        grupo.classList.add('saindo');
        setTimeout(() => grupo.remove(), 380);
      } else {
        grupo.remove();
      }
    });

    porcoes.forEach((p) => {
      const chave = `${p.slug}#${p.porcao}`;
      if (this.grupos.has(chave)) return;
      const grupo = this._criarGrupo(p, animar ? novas * 120 : null);
      this.grupos.set(chave, grupo);
      this.pecas.appendChild(grupo);
      if (animar) {
        novas += 1;
        this.narrar(p.porcao > 1 ? `Caprichando: mais ${p.nome.toLowerCase()}!` : `Colocando ${p.nome.toLowerCase()}…`);
      }
    });
    this.pizza.classList.remove('assada');
  }

  /** Remonta a pizza do zero, passo a passo, e termina no forno. */
  async reproduzir({ massa, molho, porcoes, tamanhoNome }) {
    if (this.reproduzindo) return;
    this.reproduzindo = true;
    const passo = SEM_ANIMACAO ? 0 : 1;
    try {
      this.grupos.forEach((g) => g.remove());
      this.grupos.clear();
      this.pizza.classList.remove('assando', 'assada');
      this.molho.classList.add('vazio');
      this.narrar(`Pizza ${tamanhoNome.toLowerCase()}: vamos começar!`);
      await esperar(500 * passo);

      this.setMassa(massa.slug, massa.nome, massa.cor_hex);
      await esperar(900 * passo);

      this.molho.classList.remove('vazio');
      this.setMolho(molho.slug, molho.nome, molho.cor_hex);
      await esperar(1000 * passo);

      for (const p of porcoes) {
        this.setCoberturas([...this.grupos.keys()].map(chaveParaPorcao(porcoes)).filter(Boolean).concat([p]));
        await esperar(650 * passo);
      }
      await this.assar();
    } finally {
      this.molho.classList.remove('vazio');
      this.reproduzindo = false;
    }
  }

  /** Efeito de forno: brilho alaranjado e a pizza fica dourada. */
  async assar() {
    this.narrar('Indo para o forno a lenha… 🔥');
    this.pizza.classList.remove('assada');
    this._reiniciarAnimacao(this.pizza, 'assando');
    await esperar(SEM_ANIMACAO ? 0 : 1700);
    this.pizza.classList.remove('assando');
    this.pizza.classList.add('assada');
    this.narrar('Pronta! Saindo quentinha. 🍕');
  }

  _criarGrupo(p, atrasoBase) {
    const cfg = PECAS_COBERTURA[p.slug] || { forma: 'disco', n: 7, tam: [8, 10], cores: [p.cor || '#C1391F', p.cor || '#9A2C17'] };
    const sorteio = geradorSemente(`${p.slug}#${p.porcao}`);
    const grupo = document.createElement('div');
    grupo.className = 'grupo-cobertura';
    grupo.dataset.slug = p.slug;
    for (let i = 0; i < cfg.n; i++) {
      // distribuição uniforme no disco (raiz quadrada no raio), longe da borda
      const raio = Math.sqrt(sorteio()) * 40;
      const angulo = sorteio() * Math.PI * 2;
      const tam = cfg.tam[0] + sorteio() * (cfg.tam[1] - cfg.tam[0]);
      const peca = document.createElement('i');
      peca.className = `peca forma-${cfg.forma}`;
      peca.style.cssText = [
        `--x:${50 + raio * Math.cos(angulo)}%`,
        `--y:${50 + raio * Math.sin(angulo)}%`,
        `--s:${tam}%`,
        `--r:${Math.round(sorteio() * 360)}deg`,
        `--c1:${cfg.cores[0]}`,
        `--c2:${cfg.cores[1]}`,
        `--atraso:${atrasoBase === null ? 0 : atrasoBase + i * 45}ms`,
      ].join(';');
      if (atrasoBase === null) peca.classList.add('parada');
      grupo.appendChild(peca);
    }
    return grupo;
  }

  _farinha() {
    if (SEM_ANIMACAO) return;
    const sorteio = geradorSemente(String(Date.now()));
    for (let i = 0; i < 14; i++) {
      const p = document.createElement('i');
      p.className = 'farinha';
      const ang = sorteio() * Math.PI * 2;
      p.style.cssText = `--dx:${Math.cos(ang) * (40 + sorteio() * 30)}%;--dy:${Math.sin(ang) * (40 + sorteio() * 30)}%;--atraso:${Math.round(sorteio() * 200)}ms`;
      this.palco.appendChild(p);
      setTimeout(() => p.remove(), 1300);
    }
  }

  _reiniciarAnimacao(el, classe) {
    el.classList.remove(classe);
    void el.offsetWidth; // força o navegador a recomeçar a animação
    el.classList.add(classe);
  }
}

// usado no replay para manter as porções já colocadas
function chaveParaPorcao(porcoes) {
  return (chave) => porcoes.find((p) => `${p.slug}#${p.porcao}` === chave);
}
