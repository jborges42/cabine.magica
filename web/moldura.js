const FONTE = '"Marca", "Century Gothic", sans-serif';
const FORMATOS = [
  { id: "story", nome: "Story", proporcao: 9 / 16, rotulo: "9:16" },
  { id: "feed", nome: "Feed", proporcao: 4 / 5, rotulo: "4:5" },
  { id: "quadrado", nome: "Quadrado", proporcao: 1, rotulo: "1:1" },
  { id: "grande", nome: "Grande", proporcao: null, rotulo: "inteira" },
];

// Proporções da barra lateral oficial (ref/barra_lateral.png), em múltiplos da largura da barra:
// laranja até 2,51 (esq.) / 1,78 (dir.), vão, azul a partir de 3,79 / 3,06 → corte diagonal de ~36°.
const BARRA = { laranja: [2.51, 1.78], azul: [3.79, 3.06], canto: 0.18, inclinacao: 0.73 };

function desenharMoldura(g, L, A, cfg, logo) {
  const u = Math.min(L, A) / 100; // tudo proporcional: funciona em 720p, 1080p, 4K ou retrato
  const barra = 4.6 * u, faixa = 15 * u, curva = 3 * u, respiro = 3.2 * u;
  const base = A - faixa; // topo da faixa azul

  // Barra lateral SENAI: bloco laranja, vão diagonal (a foto aparece) e azul que desce e vira a faixa.
  g.fillStyle = cfg.cor_destaque;
  g.beginPath();
  g.moveTo(0, 0);
  g.arcTo(barra, 0, barra, barra, BARRA.canto * barra);
  g.lineTo(barra, BARRA.laranja[1] * barra);
  g.lineTo(0, BARRA.laranja[0] * barra);
  g.fill();
  g.fillStyle = cfg.cor_primaria;
  g.beginPath();
  g.moveTo(0, BARRA.azul[0] * barra);
  g.lineTo(barra, BARRA.azul[1] * barra);
  g.arcTo(barra, base, barra + curva, base, curva);
  g.lineTo(L, base);
  g.lineTo(L, A);
  g.lineTo(0, A);
  g.fill();

  // Bandeira da hashtag: laranja, apoiada na faixa, com o mesmo corte diagonal da barra.
  const alturaBandeira = 8.4 * u;
  const larguraHashtag = ajustar(g, cfg.hashtag, 700, 4.6 * u, L * 0.35);
  const corte = alturaBandeira / BARRA.inclinacao;
  const inicioTexto = L - respiro - larguraHashtag;
  const xBandeira = inicioTexto - respiro - corte / 2;
  g.fillStyle = cfg.cor_destaque;
  g.beginPath();
  g.moveTo(xBandeira, base);
  g.lineTo(xBandeira + corte, base - alturaBandeira);
  g.lineTo(L, base - alturaBandeira);
  g.lineTo(L, base);
  g.fill();
  g.fillStyle = "#fff";
  g.textAlign = "left";
  g.textBaseline = "middle";
  g.fillText(cfg.hashtag, inicioTexto, base - alturaBandeira / 2);

  // Faixa: título + unidade à esquerda, divisor e assinatura SENAI à direita (como no modelo oficial).
  const meio = base + faixa / 2;
  const margem = barra + respiro;
  let limite = L - respiro;
  if (logo) {
    const alturaLogo = 5.4 * u, larguraLogo = (alturaLogo * logo.width) / logo.height;
    limite -= larguraLogo;
    g.drawImage(logo, limite, meio - alturaLogo / 2, larguraLogo, alturaLogo);
    limite -= respiro;
    g.fillStyle = "rgb(255 255 255 / .45)";
    g.fillRect(limite, meio - 3.4 * u, 0.18 * u, 6.8 * u);
    limite -= respiro;
  }
  g.fillStyle = "#fff";
  g.textBaseline = "alphabetic";
  ajustar(g, cfg.titulo, 700, 5.2 * u, limite - margem);
  g.fillText(cfg.titulo, margem, meio + 0.2 * u);
  g.letterSpacing = `${0.55 * u}px`;
  g.fillStyle = "rgb(255 255 255 / .8)";
  ajustar(g, cfg.unidade, 400, 2.3 * u, limite - margem);
  g.fillText(cfg.unidade, margem, meio + 4.3 * u);
  g.letterSpacing = "0px";
}

// Define a fonte (e o espaçamento) e reduz o tamanho se o texto não couber em `max`.
function ajustar(g, texto, peso, tamanho, max) {
  g.font = `${peso} ${tamanho}px ${FONTE}`;
  const largura = g.measureText(texto).width;
  if (largura > max) {
    const k = max / largura;
    g.font = `${peso} ${tamanho * k}px ${FONTE}`;
    g.letterSpacing = `${parseFloat(g.letterSpacing) * k}px`;
  }
  return Math.min(largura, max);
}
