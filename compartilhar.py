"""Download da foto no celular do visitante (QR Code na tela), de graça.

Um servidor SEPARADO (porta 8766) responde só /f/<id>/<assinatura>: a página com a foto e o
arquivo em qualidade total. Um túnel gratuito (Cloudflare Quick Tunnel, sem conta) dá a ele
um endereço HTTPS público; o resto da cabine continua acessível só no próprio PC.
"""
import atexit
import base64
import hashlib
import hmac
import re
import secrets
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent
SEGREDO = RAIZ / "segredo.key"  # assina os links; apague ao fim do evento e os links antigos param
PORTA = 8766
estado = {"url": None, "erro": None}
_segredo = []

PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sua foto · Cabine Mágica SENAI</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #061131; color: #fff; font: 16px/1.45 system-ui, sans-serif; }
  main { width: min(520px, 100%); padding: 20px; display: grid; gap: 14px; }
  img { width: 100%; border-radius: 14px; box-shadow: 0 20px 60px -20px #000; }
  a, button { display: block; padding: 16px; border: 0; border-radius: 12px; text-align: center; text-decoration: none; font: 700 18px system-ui, sans-serif; color: #fff; background: #E84910; }
  button { background: #164193; }
  p { margin: 0; text-align: center; color: #AFBAD8; font-size: 14px; }
</style></head><body><main>
  <img src="{foto}" alt="Sua foto da Cabine Mágica">
  <button id="compartilhar" hidden>Compartilhar (Story, WhatsApp…)</button>
  <a href="{foto}?baixar=1" download>Salvar foto em alta qualidade</a>
  <p>No iPhone, se preferir, toque e segure a foto e escolha “Salvar em Fotos”.</p>
</main><script>
  const botao = document.getElementById("compartilhar");
  fetch("{foto}").then((r) => r.blob()).then((blob) => {
    const arquivo = new File([blob], "foto-cabine-magica.jpg", { type: "image/jpeg" });
    if (navigator.canShare?.({ files: [arquivo] })) {
      botao.hidden = false;
      botao.onclick = () => navigator.share({ files: [arquivo] }).catch(() => {});
    }
  });
</script></body></html>"""


def assinatura(foto_id):
    if not _segredo:
        if not SEGREDO.exists():
            SEGREDO.write_bytes(secrets.token_bytes(32))
        _segredo.append(SEGREDO.read_bytes())
    digest = hmac.new(_segredo[0], foto_id.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:12]).decode()  # 96 bits: impossível adivinhar


def link(foto_id):
    return f"{estado['url']}/f/{foto_id}/{assinatura(foto_id)}" if estado["url"] else None


class Publico(BaseHTTPRequestHandler):
    fotos = None

    def do_GET(self):
        url = urlsplit(self.path)
        achado = re.fullmatch(r"/f/(\d{8}-\d{6}-[0-9a-f]{6})/([\w-]{16})(/foto\.jpg)?", url.path)
        arquivo = self.fotos / f"{achado[1]}.jpg" if achado else None
        if not achado or not hmac.compare_digest(achado[2], assinatura(achado[1])) or not arquivo.exists():
            return self.enviar(404, "Foto não encontrada.".encode(), "text/plain; charset=utf-8")
        if not achado[3]:
            return self.enviar(200, PAGINA.replace("{foto}", f"{url.path}/foto.jpg").encode(), "text/html; charset=utf-8")
        modo = "attachment" if "baixar" in url.query else "inline"
        self.enviar(200, arquivo.read_bytes(), "image/jpeg", f'{modo}; filename="cabine-magica-{achado[1]}.jpg"')

    def enviar(self, status, corpo, tipo, disposicao=None):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        if disposicao:
            self.send_header("Content-Disposition", disposicao)
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass


def _tunel():
    """Cloudflare Quick Tunnel: lê a URL https://*.trycloudflare.com da saída do cloudflared.
    Se o túnel cair (internet do evento), sobe outro; cada foto nova já pega a URL nova."""
    executavel = shutil.which("cloudflared") or next((str(p) for p in RAIZ.glob("cloudflared*") if p.is_file()), None)
    if not executavel:
        estado["erro"] = "cloudflared não instalado: o QR de download fica desligado"
        return
    while True:
        processo = subprocess.Popen(
            [executavel, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORTA}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,  # sem janela preta
        )
        atexit.register(processo.terminate)  # não deixa o túnel órfão ao fechar a cabine
        for linha in processo.stderr:  # continua lendo: o pipe cheio travaria o cloudflared
            if not estado["url"] and (achado := re.search(r"https://(?!api\.)[-a-z0-9]+\.trycloudflare\.com", linha)):
                # O DNS do endereço novo leva alguns segundos; consultado cedo, o celular guarda
                # "não existe" em cache por até 60 s. Então só mostra o QR depois.
                threading.Timer(10, estado.update, kwargs={"url": achado[0], "erro": None}).start()
        estado.update(url=None, erro=f"túnel caiu (código {processo.wait()}); reconectando")
        threading.Event().wait(10)


def iniciar(fotos):
    Publico.fotos = fotos
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Publico)  # o túnel conecta por aqui
    threading.Thread(target=servidor.serve_forever, daemon=True, name="publico").start()
    threading.Thread(target=_tunel, daemon=True, name="tunel").start()
