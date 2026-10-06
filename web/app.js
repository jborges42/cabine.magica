// Cabine Mágica — SENAI Fraiburgo
// Estados: carregando → ao-vivo → contagem → revisao → enviado → ao-vivo (ou erro)

const $ = (seletor) => document.querySelector(seletor);
const tela = $("#tela");
const ctx = tela.getContext("2d");
const campo = $("#whatsapp");
const enviar = $("#enviar");
const video = Object.assign(document.createElement("video"), { muted: true, playsInline: true });
const reduzirMovimento = matchMedia("(prefers-reduced-motion: reduce)").matches;
const DISPARO = new Set(["Enter", " ", "PageDown", "PageUp"]); // teclado, teclado numérico e passador de slides
const CELULAR = /^[1-9]{2}9\d{8}$/; // DDD + 9 + 8 dígitos (mesma regra do cabine.py)
const FONTE = "Unbounded, system-ui, sans-serif";
const MENSAGENS = {
  NotAllowedError: "O navegador bloqueou a câmera. Libere o acesso no ícone ao lado do endereço e tente de novo.",
  NotFoundError: "Nenhuma câmera encontrada. Conecte uma webcam USB.",
  NotReadableError: "A câmera está em uso por outro programa (Zoom, Teams, OBS…). Feche-o e tente de novo.",
  Desconectada: "A câmera foi desconectada. Reconecte o cabo — a cabine volta sozinha.",
};
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms));

let cfg, moldura, camada, stream, estado, upload, timer;
let cameras = [];
let revisaoDesde = 0;

function mudar(novo) {
  estado = novo;
  document.body.dataset.estado = novo;
}

async function iniciar() {
  cfg = await (await fetch("config.json")).json();
  for (const chave in cfg) {
    if (chave.startsWith("cor_")) document.documentElement.style.setProperty(`--${chave.replaceAll("_", "-")}`, cfg[chave]);
  }
  if (cfg.moldura_png) {
    const img = new Image();
    img.src = cfg.moldura_png;
    moldura = await img.decode().then(() => img, () => console.warn("moldura_png não carregou; usando a moldura desenhada"));
  }
  // Fonte da moldura: espera no máximo 2 s (sem internet, segue com a do sistema).
  await Promise.race([document.fonts.load(`900 10px ${FONTE}`), document.fonts.load(`600 10px ${FONTE}`), espera(2000)]);
  document.fonts.onloadingdone = () => (camada = null);
  await abrirCamera(localStorage.getItem("camera"));
  requestAnimationFrame(quadro);
}

async function abrirCamera(id) {
  mudar("carregando");
  stream?.getTracks().forEach((trilha) => trilha.stop());
  const [largura, altura] = cfg.resolucao;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { deviceId: id ? { exact: id } : undefined, width: { ideal: largura }, height: { ideal: altura } },
    });
    video.srcObject = stream;
    await video.play();
  } catch (erro) {
    if (id) return abrirCamera(); // a câmera salva sumiu: tenta a padrão
    return falha(MENSAGENS[erro.name] || `Não foi possível abrir a câmera (${erro.name}: ${erro.message}).`);
  }
  const trilha = stream.getVideoTracks()[0];
  trilha.onended = () => {
    // Durante a revisão não interrompe quem está digitando; a câmera é reaberta ao voltar.
    if (estado === "ao-vivo" || estado === "contagem") falha(MENSAGENS.Desconectada);
  };
  localStorage.setItem("camera", trilha.getSettings().deviceId);
  cameras = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
  $("#camera").textContent = trilha.label || "Câmera conectada";
  mudar("ao-vivo");
}

function trocarCamera() {
  if (cameras.length < 2) return;
  const atual = cameras.findIndex((c) => c.deviceId === stream.getVideoTracks()[0].getSettings().deviceId);
  abrirCamera(cameras[(atual + 1) % cameras.length].deviceId);
}

function falha(mensagem) {
  $("#erro-msg").textContent = mensagem;
  $("#camera").textContent = "Sem câmera";
  mudar("erro");
  $("#tentar").focus();
}

// ---------- desenho: vídeo + moldura ----------

function quadro() {
  if (estado === "ao-vivo" || estado === "contagem") compor();
  requestAnimationFrame(quadro);
}

function compor() {
  const { videoWidth: L, videoHeight: A } = video;
  if (!L) return;
  if (tela.width !== L || tela.height !== A) [tela.width, tela.height] = [L, A];
  if (cfg.espelhar) ctx.setTransform(-1, 0, 0, 1, L, 0); // prévia tipo espelho, como o celular
  ctx.drawImage(video, 0, 0, L, A);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  // A moldura é estática: desenha uma vez numa camada e só a cola a cada quadro.
  if (camada?.width !== L || camada?.height !== A) camada = criarCamada(L, A);
  ctx.drawImage(camada, 0, 0);
}

function criarCamada(L, A) {
  const c = Object.assign(document.createElement("canvas"), { width: L, height: A });
  const g = c.getContext("2d");
  if (moldura) g.drawImage(moldura, 0, 0, L, A);
  else desenharMoldura(g, L, A);
  return c;
}

function desenharMoldura(g, L, A) {
  const u = Math.min(L, A) / 100; // tudo proporcional: funciona em 720p, 1080p, 4K ou retrato
  const borda = 2.4 * u, faixa = 17 * u, raio = 3.2 * u;
  const janela = [borda, borda, L - 2 * borda, A - borda - faixa, raio];

  // Faixa colorida com a janela da foto vazada
  const fundo = g.createLinearGradient(0, 0, L, A);
  fundo.addColorStop(0, cfg.cor_inicio);
  fundo.addColorStop(1, cfg.cor_fim);
  g.fillStyle = fundo;
  g.beginPath();
  g.rect(0, 0, L, A);
  g.roundRect(...janela);
  g.fill("evenodd");
  g.strokeStyle = "rgb(255 255 255 / .35)";
  g.lineWidth = 0.3 * u;
  g.beginPath();
  g.roundRect(...janela);
  g.stroke();

  const meio = A - faixa / 2;
  const margem = 2 * borda;

  // Selo da hashtag, levemente inclinado
  const larguraHashtag = ajustar(g, cfg.hashtag, 900, 5.6 * u, L * 0.4);
  const sl = larguraHashtag + 6 * u, sa = 10 * u;
  const sx = L - margem - sl / 2;
  g.save();
  g.translate(sx, meio);
  g.rotate(-4 * Math.PI / 180);
  g.shadowColor = "rgb(0 0 0 / .35)";
  g.shadowBlur = 2.4 * u;
  g.shadowOffsetY = 0.8 * u;
  g.fillStyle = cfg.cor_destaque;
  g.beginPath();
  g.roundRect(-sl / 2, -sa / 2, sl, sa, 2.6 * u);
  g.fill();
  g.shadowColor = "transparent";
  g.fillStyle = cfg.cor_texto_destaque;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(cfg.hashtag, 0, 0.3 * u);
  g.restore();
  g.fillStyle = "#fff";
  brilho(g, sx - sl / 2 - 0.8 * u, meio - sa / 2 - 0.6 * u, 1.8 * u);
  brilho(g, sx + sl / 2 + 0.4 * u, meio + sa / 2 + 0.2 * u, 1.1 * u);

  // Título e subtítulo à esquerda
  const livre = sx - sl / 2 - 4 * u - margem;
  g.textAlign = "left";
  g.textBaseline = "alphabetic";
  g.fillStyle = "#fff";
  ajustar(g, cfg.titulo, 900, 6.2 * u, livre);
  g.fillText(cfg.titulo, margem, meio + 0.6 * u);
  g.letterSpacing = `${0.9 * u}px`;
  g.fillStyle = "rgb(255 255 255 / .8)";
  ajustar(g, cfg.subtitulo, 600, 2.6 * u, livre);
  g.fillText(cfg.subtitulo, margem, meio + 5.4 * u);
  g.letterSpacing = "0px";
}

// Define a fonte e reduz o tamanho se o texto não couber em `max`. Retorna a largura final.
function ajustar(g, texto, peso, tamanho, max) {
  g.font = `${peso} ${tamanho}px ${FONTE}`;
  const largura = g.measureText(texto).width;
  if (largura > max) g.font = `${peso} ${(tamanho * max) / largura}px ${FONTE}`;
  return Math.min(largura, max);
}

// Estrela de quatro pontas ✦
function brilho(g, x, y, r) {
  g.beginPath();
  g.moveTo(x, y - r);
  g.quadraticCurveTo(x, y, x + r, y);
  g.quadraticCurveTo(x, y, x, y + r);
  g.quadraticCurveTo(x, y, x - r, y);
  g.quadraticCurveTo(x, y, x, y - r);
  g.fill();
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
  compor();
  if (!reduzirMovimento) $("#flash").animate([{ opacity: 0.9 }, { opacity: 0 }], { duration: 500, easing: "ease-out" });
  const foto = await new Promise((ok) => tela.toBlob(ok, "image/jpeg", cfg.qualidade_jpeg));
  upload = postar("api/fotos", foto, "image/jpeg").then((r) => r.id);
  upload.catch(() => mostrarErro("Não conseguimos salvar a foto. Tire outra, por favor."));
  URL.revokeObjectURL($("#foto").src); // evita acumular memória ao longo do evento
  $("#foto").src = URL.createObjectURL(foto);
  abrirRevisao();
}

async function postar(rota, corpo, tipo) {
  const resposta = await fetch(rota, { method: "POST", headers: { "Content-Type": tipo }, body: corpo });
  const dados = await resposta.json();
  if (!resposta.ok) throw new Error(dados.erro);
  return dados;
}

function abrirRevisao() {
  campo.value = "";
  atualizarFormulario();
  mudar("revisao");
  campo.focus();
  revisaoDesde = performance.now();
  inatividade(60_000);
}

function mascara(digitos) {
  const d = digitos.replace(/\D/g, "").slice(0, 11);
  if (d.length > 7) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length > 2) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  return d && `(${d}`;
}

function atualizarFormulario() {
  enviar.firstElementChild.textContent = campo.value ? "Enviar para meu WhatsApp" : "Pular e concluir";
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
  // Ignora o Enter que vem "colado" do disparo da foto.
  if (performance.now() - revisaoDesde < 800 || enviar.disabled) return;
  const digitos = campo.value.replace(/\D/g, "");
  if (!digitos) return concluir("Valeu pela visita!", "Sua foto ficou guardada aqui na cabine.");
  if (!CELULAR.test(digitos)) return mostrarErro("Confira o número: DDD + celular com 9 dígitos.");
  enviar.disabled = true;
  try {
    await postar("api/envios", JSON.stringify({ id: await upload, whatsapp: digitos }), "application/json");
    concluir("Prontinho!", `Sua foto será enviada para o WhatsApp ${campo.value}.`);
  } catch {
    mostrarErro("Não deu para registrar o envio. Tente de novo.");
  } finally {
    enviar.disabled = false;
  }
});

function concluir(titulo, mensagem) {
  $("#final-titulo").textContent = titulo;
  $("#final-msg").textContent = mensagem;
  mudar("enviado");
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
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen();
}

// ---------- teclado e toque ----------

addEventListener("keydown", (evento) => {
  if (evento.repeat) return;
  const tecla = evento.key.toLowerCase();
  if (estado === "ao-vivo") {
    if (DISPARO.has(evento.key)) {
      evento.preventDefault();
      fotografar();
    } else if (tecla === "c") trocarCamera();
    else if (tecla === "f") telaCheia();
  } else if (estado === "revisao") {
    if (evento.key === "Escape") voltarAoVivo();
    else if (evento.target !== campo && /^\d$/.test(evento.key)) campo.focus();
  } else if (estado === "enviado") {
    evento.preventDefault();
    voltarAoVivo();
  }
});

$("#disparo").addEventListener("click", fotografar);
tela.addEventListener("click", fotografar);
$("#refazer").addEventListener("click", voltarAoVivo);
navigator.mediaDevices.addEventListener("devicechange", () => {
  if (estado === "erro") location.reload(); // webcam reconectada: volta sozinha
});

iniciar().catch((erro) => falha(`Não foi possível iniciar a cabine: ${erro.message}`));
