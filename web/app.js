// Cabine Mágica — SENAI Fraiburgo
// Estados: carregando → ao-vivo → contagem → revisao → enviado → ao-vivo (ou erro)

const $ = (seletor) => document.querySelector(seletor);
const tela = $("#tela");
const ctx = tela.getContext("2d");
const campo = $("#whatsapp");
const enviar = $("#enviar");
const foto = $("#foto");
const video = Object.assign(document.createElement("video"), { muted: true, playsInline: true });
const reduzirMovimento = matchMedia("(prefers-reduced-motion: reduce)").matches;
const DISPARO = new Set(["Enter", " ", "PageDown", "PageUp"]); // teclado, teclado numérico e passador de slides
const CELULAR = /^[1-9]{2}9\d{8}$/; // DDD + 9 + 8 dígitos (mesma regra do cabine.py)
const FONTE = '"Marca", "Century Gothic", sans-serif'; // Century Gothic da identidade SENAI (ver @font-face)
const PADRAO = { titulo: "", unidade: "", hashtag: "", espelhar_previa: true, espelhar_foto: true, contagem: 3, resolucao: "max", fps: 30, preset: "natural", formato: "feed" };
// Formatos da foto (teclas 1–4 na tela ao vivo): recorte central do vídeo na proporção escolhida.
const FORMATOS = [
  { id: "story", nome: "Story", proporcao: 9 / 16, rotulo: "9:16" },
  { id: "feed", nome: "Feed", proporcao: 4 / 5, rotulo: "4:5" },
  { id: "quadrado", nome: "Quadrado", proporcao: 1, rotulo: "1:1" },
  { id: "grande", nome: "Grande", proporcao: null, rotulo: "inteira" },
];
const MENSAGENS = {
  NotAllowedError: "O navegador bloqueou a câmera. Libere o acesso no ícone ao lado do endereço e tente de novo.",
  NotFoundError: "Nenhuma câmera encontrada. Conecte uma webcam USB.",
  NotReadableError: "A câmera está em uso por outro programa (Zoom, Teams, OBS…). Feche-o e tente de novo.",
  TimeoutError: "A câmera conectou mas não manda imagem. Verifique se está ligada (ou se a placa de captura tem sinal).",
  Desconectada: "A câmera foi desconectada. Reconecte o cabo — a cabine volta sozinha.",
};
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms));

let cfg, logo, moldura, stream, estado, upload, timer, presetAtual, formato;
let cameras = [];
let presets = [];
let tratando = Promise.resolve();
let marco = 0; // quando a revisão/conclusão abriu: ignora o Enter "colado" da tela anterior
let sessao = 0; // muda a cada foto: respostas atrasadas de um visitante não aparecem para o próximo
const camadas = new Map(); // moldura pré-desenhada por tamanho
const moldurasEnviadas = new Map(); // tamanho → upload da camada para o servidor

function mudar(novo) {
  estado = novo;
  document.body.dataset.estado = novo;
}

async function iniciar() {
  const resposta = await fetch("config.json");
  try {
    cfg = { ...PADRAO, ...(await resposta.json()) };
  } catch (erro) {
    throw new Error(`web/config.json tem um erro de digitação (${erro.message})`);
  }
  for (const chave in cfg) {
    if (chave.startsWith("cor_")) document.documentElement.style.setProperty(`--${chave.replaceAll("_", "-")}`, cfg[chave]);
  }
  $(".sobretitulo").textContent = [cfg.titulo, cfg.hashtag].filter(Boolean).join(" · ");
  presets = await (await fetch("api/presets")).json();
  if (!presets.some((p) => p.id === cfg.preset)) throw new Error(`web/config.json: preset "${cfg.preset}" não existe (use ${presets.map((p) => p.id).join(", ")})`);
  formato = FORMATOS.find((f) => f.id === cfg.formato) ?? FORMATOS[0];
  logo = await imagem(cfg.logo).catch(() => console.warn("logo não carregou"));
  if (cfg.moldura_png) moldura = await imagem(cfg.moldura_png).catch(() => console.warn("moldura_png não carregou; usando a moldura desenhada"));
  await Promise.race([document.fonts.load(`700 10px ${FONTE}`), document.fonts.load(`400 10px ${FONTE}`), espera(2000)]);
  document.fonts.onloadingdone = () => {
    camadas.clear();
    moldurasEnviadas.clear();
  };
  await abrirCamera(localStorage.getItem("camera"));
  manterTelaAcesa();
  requestAnimationFrame(quadro);
}

// ---------- câmera ----------

async function abrirCamera(id) {
  mudar("carregando");
  stream?.getTracks().forEach((trilha) => trilha.stop());
  // "max": pede acima de 8K e o Chrome escolhe o maior modo nativo que mantém o fps (sem isso, 640×480).
  const [largura, altura] = cfg.resolucao === "max" ? [7680, 4320] : cfg.resolucao;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: id ? { exact: id } : undefined,
        width: { ideal: largura },
        height: { ideal: altura },
        frameRate: { ideal: cfg.fps },
        resizeMode: { ideal: "none" }, // modo nativo da câmera, sem reescala do navegador
      },
    });
    video.srcObject = stream;
    await Promise.race([video.play(), espera(8000).then(() => Promise.reject(new DOMException("sem imagem", "TimeoutError")))]);
  } catch (erro) {
    // A câmera escolhida sumiu: usa a padrão sem esquecer a escolha (ela volta quando for reconectada).
    if (id && ["OverconstrainedError", "NotFoundError"].includes(erro.name)) return abrirCamera();
    return falha(MENSAGENS[erro.name] || `Não foi possível abrir a câmera (${erro.name}: ${erro.message}).`);
  }
  const trilha = stream.getVideoTracks()[0];
  trilha.onended = () => {
    // Durante a revisão não interrompe quem está digitando; a câmera é reaberta ao voltar.
    if (estado === "ao-vivo" || estado === "contagem") falha(MENSAGENS.Desconectada);
  };
  cameras = await listarCameras();
  marcarFormato();
  mudar("ao-vivo");
}

function escolherFormato(novo) {
  formato = novo;
  marcarFormato();
}

function marcarFormato() {
  const [, , l, a] = regiao().map(Math.round);
  const trilha = stream?.getVideoTracks()[0];
  $("#camera").textContent = `${trilha?.label || "Câmera"} · ${formato.nome} · ${l}×${a}`;
  $("#formatos").replaceChildren(
    ...FORMATOS.map((f, i) => {
      const botao = Object.assign(document.createElement("button"), { type: "button", disabled: Boolean(moldura) });
      botao.innerHTML = `<kbd>${i + 1}</kbd> ${f.nome} <small>${f.rotulo}</small>`;
      botao.setAttribute("aria-pressed", f === formato);
      botao.onclick = () => escolherFormato(f);
      return botao;
    }),
  );
  if (l) enviarMoldura(l, a).catch(() => {}); // adianta o upload da moldura deste tamanho
}

const listarCameras = async () => (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
const cameraAtual = () => stream?.getVideoTracks()[0]?.getSettings().deviceId;

async function trocarCamera() {
  cameras = await listarCameras(); // pega webcams plugadas depois de abrir
  if (cameras.length < 2) return;
  const atual = cameras.findIndex((c) => c.deviceId === cameraAtual());
  const proxima = cameras[(atual + 1) % cameras.length].deviceId;
  localStorage.setItem("camera", proxima); // só a escolha explícita fica memorizada
  abrirCamera(proxima);
}

function falha(mensagem) {
  clearTimeout(timer);
  $("#erro-msg").textContent = mensagem;
  $("#camera").textContent = "Atenção necessária";
  mudar("erro");
  $("#tentar").focus();
}

function manterTelaAcesa() {
  const pedir = () => navigator.wakeLock?.request("screen").catch(() => {});
  pedir();
  document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && pedir());
}

// ---------- desenho: vídeo + moldura ----------

// Parte do vídeo que vira foto: o centro na proporção do formato (ou da moldura_png, se houver).
function regiao() {
  const { videoWidth: vl, videoHeight: va } = video;
  const proporcao = moldura ? moldura.naturalWidth / moldura.naturalHeight : formato?.proporcao;
  if (!proporcao) return [0, 0, vl, va];
  const l = Math.min(vl, va * proporcao);
  return [(vl - l) / 2, (va - l / proporcao) / 2, l, l / proporcao];
}

function desenharVideo(g, L, A, espelhar) {
  const [x, y, l, a] = regiao();
  if (espelhar) g.setTransform(-1, 0, 0, 1, L, 0);
  g.drawImage(video, x, y, l, a, 0, 0, L, A);
  g.setTransform(1, 0, 0, 1, 0, 0);
}

// A prévia é desenhada no tamanho da tela (leve até com câmera 4K); a foto, em resolução total.
function quadro() {
  if ((estado === "ao-vivo" || estado === "contagem") && video.videoWidth) {
    const [, , l, a] = regiao();
    const escala = Math.min(1, (screen.width * devicePixelRatio) / l, (screen.height * devicePixelRatio) / a);
    const L = Math.round(l * escala), A = Math.round(a * escala);
    if (tela.width !== L || tela.height !== A) [tela.width, tela.height] = [L, A];
    desenharVideo(ctx, L, A, cfg.espelhar_previa); // prévia tipo espelho, como o celular
    ctx.drawImage(camada(L, A), 0, 0);
  }
  requestAnimationFrame(quadro);
}

function camada(L, A) {
  const chave = `${L}x${A}`;
  if (!camadas.has(chave)) {
    const c = Object.assign(document.createElement("canvas"), { width: L, height: A });
    const g = c.getContext("2d");
    if (moldura) g.drawImage(moldura, 0, 0, L, A);
    else desenharMoldura(g, L, A);
    camadas.set(chave, c);
  }
  return camadas.get(chave);
}

// O servidor cola esta mesma camada na foto tratada: a moldura tem uma única fonte de verdade.
function enviarMoldura(L, A) {
  const chave = `${L}x${A}`;
  if (!moldurasEnviadas.has(chave)) {
    const envio = new Promise((ok) => camada(L, A).toBlob(ok, "image/png")).then((png) => postar("api/moldura", png, "image/png"));
    envio.catch(() => moldurasEnviadas.delete(chave));
    moldurasEnviadas.set(chave, envio);
  }
  return moldurasEnviadas.get(chave);
}

// Proporções da barra lateral oficial (ref/barra_lateral.png), em múltiplos da largura da barra:
// laranja até 2,51 (esq.) / 1,78 (dir.), vão, azul a partir de 3,79 / 3,06 → corte diagonal de ~36°.
const BARRA = { laranja: [2.51, 1.78], azul: [3.79, 3.06], canto: 0.18, inclinacao: 0.73 };

function desenharMoldura(g, L, A) {
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

async function imagem(src) {
  const img = new Image();
  img.crossOrigin = "anonymous"; // imagem de outro site sem CORS falha aqui, e não na hora da foto
  img.src = src;
  await img.decode();
  return img;
}

// ---------- fluxo da foto ----------

async function fotografar() {
  if (estado !== "ao-vivo") return;
  mudar("contagem");
  const numero = $("#contagem");
  for (let n = cfg.contagem; n > 0; n--) {
    numero.textContent = n;
    if (!reduzirMovimento) {
      numero.animate(
        [{ opacity: 0, transform: "scale(1.8)" }, { opacity: 1, transform: "scale(1)", offset: 0.3 }, { opacity: 0, transform: "scale(.85)" }],
        { duration: 1000, easing: "cubic-bezier(.2,.8,.2,1)", fill: "forwards" },
      );
    }
    await espera(1000);
    if (estado !== "contagem") return; // câmera caiu no meio da contagem
  }
  numero.textContent = "";

  // Original em resolução total, sem moldura: o servidor trata e cola a moldura depois.
  const [, , l, a] = regiao().map(Math.round);
  const quadroTotal = Object.assign(document.createElement("canvas"), { width: l, height: a });
  desenharVideo(quadroTotal.getContext("2d"), l, a, cfg.espelhar_foto); // sem espelho: banners e camisetas legíveis
  if (!reduzirMovimento) $("#flash").animate([{ opacity: 0.9 }, { opacity: 0 }], { duration: 500, easing: "ease-out" });
  // Prévia leve, igual à foto final (mesmo espelhamento), para aparecer na hora enquanto o servidor trata.
  const miniatura = Object.assign(document.createElement("canvas"), { width: tela.width, height: tela.height });
  const g = miniatura.getContext("2d");
  g.drawImage(quadroTotal, 0, 0, tela.width, tela.height);
  g.drawImage(camada(tela.width, tela.height), 0, 0);
  const [original, previa] = await Promise.all([
    new Promise((ok) => quadroTotal.toBlob(ok, "image/jpeg", 0.95)),
    new Promise((ok) => miniatura.toBlob(ok, "image/jpeg", 0.85)),
  ]);

  const minha = ++sessao;
  presetAtual = cfg.preset;
  mostrarFoto(URL.createObjectURL(previa));
  upload = enviarMoldura(l, a)
    .catch(() => {}) // sem moldura a foto ainda é salva
    .then(() => postar(`api/fotos?preset=${presetAtual}`, original, "image/jpeg"))
    .then(({ id }) => {
      if (minha === sessao && presetAtual === cfg.preset) mostrarFoto(`fotos/${id}.jpg?v=${Date.now()}`);
      if (minha === sessao) mostrarQr(id, minha);
      return id;
    });
  upload.catch(() => minha === sessao && falha("A foto não foi salva. Verifique se a janela do cabine.py está aberta e se há espaço em disco."));
  tratando = upload;
  foto.classList.remove("tratando");
  abrirRevisao();
}

// QR Code para o visitante baixar a foto no celular (só aparece se o túnel público estiver no ar).
async function mostrarQr(id, minha) {
  const { qr } = await fetch(`api/fotos/${id}/link`).then((r) => r.json()).catch(() => ({}));
  if (!qr || minha !== sessao || estado !== "revisao") return;
  $("#qr").innerHTML = qr; // SVG gerado pelo próprio servidor
  $("#baixar").hidden = false;
}

function mostrarFoto(src) {
  if (foto.src.startsWith("blob:")) URL.revokeObjectURL(foto.src); // evita acumular memória no evento
  foto.src = src;
}

// Troca o ajuste (Natural, Luz de estúdio…). Só o último pedido importa; a fila evita corrida no servidor.
function trocarPreset(passo) {
  const i = presets.findIndex((p) => p.id === presetAtual);
  presetAtual = presets[(i + passo + presets.length) % presets.length].id;
  const escolhido = presetAtual;
  const minha = sessao;
  const doVisitante = upload;
  marcarPresets();
  inatividade(60_000);
  foto.classList.add("tratando");
  tratando = tratando.catch(() => {}).then(async () => {
    if (escolhido !== presetAtual || minha !== sessao) return; // já trocaram de novo ou é outra foto
    try {
      const id = await doVisitante;
      await postar(`api/fotos/${id}/preset`, JSON.stringify({ preset: escolhido }), "application/json");
      if (escolhido === presetAtual && minha === sessao) mostrarFoto(`fotos/${id}.jpg?v=${Date.now()}`);
    } finally {
      if (escolhido === presetAtual && minha === sessao) foto.classList.remove("tratando");
    }
  });
}

function marcarPresets() {
  $("#presets").replaceChildren(
    ...presets.map((p) => {
      const botao = Object.assign(document.createElement("button"), { type: "button", textContent: p.nome });
      botao.setAttribute("aria-pressed", p.id === presetAtual);
      botao.onclick = () => trocarPreset(presets.indexOf(p) - presets.findIndex((q) => q.id === presetAtual));
      return botao;
    }),
  );
}

async function postar(rota, corpo, tipo) {
  const resposta = await fetch(rota, { method: "POST", headers: { "Content-Type": tipo }, body: corpo, signal: AbortSignal.timeout(20_000) });
  const dados = await resposta.json();
  if (!resposta.ok) throw new Error(dados.erro);
  return dados;
}

function abrirRevisao() {
  $("#baixar").hidden = true;
  enviar.disabled = false;
  campo.value = "";
  atualizarFormulario();
  marcarPresets();
  mudar("revisao");
  campo.focus();
  marco = performance.now();
  inatividade(60_000);
}

function mascara(digitos) {
  const d = digitos.replace(/\D/g, "").slice(0, 11);
  if (d.length > 7) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length > 2) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  return d && `(${d}`;
}

function atualizarFormulario() {
  enviar.firstElementChild.textContent = campo.value ? "Enviar foto" : "Pular e concluir";
  campo.removeAttribute("aria-invalid");
  $("#erro").textContent = "";
}

function mostrarErro(mensagem) {
  $("#erro").textContent = mensagem;
  campo.setAttribute("aria-invalid", "true");
}

campo.addEventListener("input", () => {
  campo.value = mascara(campo.value);
  atualizarFormulario();
  inatividade(60_000);
});

$("#form").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (performance.now() - marco < 800 || enviar.disabled) return; // Enter "colado" do disparo
  const digitos = campo.value.replace(/\D/g, "");
  if (digitos && !CELULAR.test(digitos)) return mostrarErro("Confira o número: DDD + celular com 9 dígitos.");
  const minha = sessao; // o envio é deste visitante, mesmo que o próximo já esteja na tela
  enviar.disabled = true;
  try {
    const id = await upload.catch(() => null);
    if (!id) return minha === sessao && mostrarErro("Não conseguimos salvar a foto. Aperte Esc e tire outra.");
    await tratando.catch(() => {}); // a foto enviada precisa estar no ajuste escolhido
    if (digitos) await postar("api/envios", JSON.stringify({ id, whatsapp: digitos }), "application/json");
    if (minha !== sessao || estado !== "revisao") return; // a revisão expirou enquanto esperava
    if (!digitos) return concluir("Valeu pela visita!", "Sua foto ficou guardada aqui na cabine.");
    concluir("Prontinho!", `Sua foto será enviada para o WhatsApp ${campo.value}.`);
    acompanharEnvio(id, campo.value);
  } catch {
    if (minha === sessao) mostrarErro("Não deu para registrar o envio. Tente de novo.");
  } finally {
    if (minha === sessao) enviar.disabled = false;
  }
});

// Mostra na tela final se o WhatsApp já entregou (quando a integração estiver configurada).
async function acompanharEnvio(id, numero) {
  for (let i = 0; i < 5 && estado === "enviado"; i++) {
    await espera(1000);
    const { status } = await fetch(`api/envios/${id}`).then((r) => r.json()).catch(() => ({}));
    if (estado !== "enviado") return;
    if (status === "enviado") return ($("#final-msg").textContent = `Foto enviada para o WhatsApp ${numero}. Confira seu celular!`);
    if (status === "erro") return ($("#final-msg").textContent = "O WhatsApp não aceitou o envio agora. A equipe vai reenviar sua foto.");
  }
}

function concluir(titulo, mensagem) {
  $("#final-titulo").textContent = titulo;
  $("#final-msg").textContent = mensagem;
  mudar("enviado");
  marco = performance.now();
  inatividade(6000);
}

function inatividade(ms) {
  clearTimeout(timer);
  timer = setTimeout(voltarAoVivo, ms);
}

function voltarAoVivo() {
  clearTimeout(timer);
  if (!stream?.active) return abrirCamera(localStorage.getItem("camera"));
  mudar("ao-vivo");
}

function telaCheia() {
  if (document.fullscreenElement) return document.exitFullscreen();
  // Prende o Esc na página (ele é "Tirar outra foto"); para sair da tela cheia, segure o Esc.
  document.documentElement.requestFullscreen().then(() => navigator.keyboard?.lock?.(["Escape"])).catch(() => {});
}

// ---------- teclado e toque ----------

addEventListener("keydown", (evento) => {
  if (evento.repeat) return;
  const tecla = evento.key.toLowerCase();
  if (estado === "ao-vivo") {
    if (DISPARO.has(evento.key)) {
      evento.preventDefault();
      fotografar();
    } else if (/^[1-4]$/.test(evento.key) && !moldura) escolherFormato(FORMATOS[evento.key - 1]);
    else if (tecla === "c") trocarCamera();
    else if (tecla === "f") telaCheia();
  } else if (estado === "revisao") {
    if (evento.key === "Escape") voltarAoVivo();
    else if (["+", "-", "ArrowRight", "ArrowLeft"].includes(evento.key)) {
      evento.preventDefault(); // + e − do teclado numérico trocam o ajuste
      trocarPreset(evento.key === "+" || evento.key === "ArrowRight" ? 1 : -1);
    } else if (/^Numpad\d$/.test(evento.code) && !/^\d$/.test(evento.key)) {
      evento.preventDefault(); // NumLock desligado: o teclado numérico manda "End", "↓"… em vez do dígito
      campo.value = mascara(campo.value + evento.code.at(-1));
      campo.dispatchEvent(new Event("input"));
    } else if (evento.target === document.body) campo.focus(); // foco perdido: a tecla vai para o campo
  } else if (estado === "enviado" && performance.now() - marco > 800) {
    evento.preventDefault();
    voltarAoVivo();
  }
});

$("#disparo").addEventListener("click", fotografar);
tela.addEventListener("click", fotografar);
$("#refazer").addEventListener("click", voltarAoVivo);
navigator.mediaDevices.addEventListener("devicechange", async () => {
  if (estado === "erro") return location.reload(); // webcam reconectada: volta sozinha
  const preferida = localStorage.getItem("camera");
  cameras = await listarCameras();
  if (estado === "ao-vivo" && preferida && preferida !== cameraAtual() && cameras.some((c) => c.deviceId === preferida)) abrirCamera(preferida);
});

iniciar().catch((erro) => falha(`Não foi possível iniciar a cabine: ${erro.message}`));
