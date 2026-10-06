"""Cabine Mágica — SENAI Fraiburgo.

Servidor local: entrega a interface (web/), trata e salva as fotos (tratamento.py) e
registra os pedidos de envio em fila/, que o whatsapp.py envia pela API oficial.
Rode com:  python cabine.py
"""
import json
import logging
import re
import secrets
import struct
import sys
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import tratamento
import whatsapp

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
FOTOS = RAIZ / "fotos"  # finais (tratadas + moldura): são as enviadas
ORIGINAIS = FOTOS / "originais"  # como saíram da câmera, para trocar o ajuste
MOLDURAS = RAIZ / "molduras"  # camada PNG da moldura por resolução, gerada pela interface
FILA = RAIZ / "fila"
PORTA = 8765
MAX_CORPO = 60 * 1024 * 1024
ID_FOTO = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
log = logging.getLogger("cabine")


def config():
    try:
        return json.loads((WEB / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar(caminho, dados):
    """Escrita atômica: quem lê (interface, envio) nunca vê arquivo pela metade."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.{secrets.token_hex(4)}.tmp")
    temporario.write_bytes(dados)
    temporario.replace(caminho)


def validar_id(foto_id):
    if not ID_FOTO.fullmatch(str(foto_id)) or not (ORIGINAIS / f"{foto_id}.jpg").exists():
        raise ValueError("foto não encontrada")
    return foto_id


def normalizar_whatsapp(numero):
    """Celular brasileiro (DDD + 9 + 8 dígitos) -> '55DD9XXXXXXXX'; inválido -> None."""
    digitos = re.sub(r"\D", "", str(numero), flags=re.ASCII)
    return "55" + digitos if re.fullmatch(r"[1-9]{2}9[0-9]{8}", digitos) else None


def salvar_moldura(png):
    if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 26 or png[25] != 6:
        raise ValueError("a moldura precisa ser PNG com transparência")
    largura, altura = struct.unpack(">II", png[16:24])
    gravar(MOLDURAS / f"{largura}x{altura}.png", png)


def tratar(foto_id, preset=None):
    """Original -> preset -> moldura -> fotos/<id>.jpg."""
    cfg = config()
    preset = preset or cfg.get("preset", "natural")
    if preset not in tratamento.PRESETS:
        raise ValueError(f"ajuste desconhecido: {preset}")
    original = (ORIGINAIS / f"{validar_id(foto_id)}.jpg").read_bytes()
    qualidade = round(float(cfg.get("qualidade_jpeg", 0.92)) * 100)
    try:
        final = tratamento.processar(original, preset, MOLDURAS, qualidade)
    except Exception:  # o ajuste falhou: a pessoa ainda recebe a foto, só sem o ajuste
        log.exception("tratamento %s falhou em %s", preset, foto_id)
        final = tratamento.processar(original, "original", MOLDURAS, qualidade)
    gravar(FOTOS / f"{foto_id}.jpg", final)


def salvar_foto(jpeg, preset=None):
    if not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("a foto precisa ser JPEG")
    foto_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    gravar(ORIGINAIS / f"{foto_id}.jpg", jpeg)  # primeiro o original: nada se perde se o resto falhar
    tratar(foto_id, preset)
    return foto_id


def enfileirar_envio(foto_id, whatsapp):
    """Cria fila/<id>.json com status 'pendente'; o whatsapp.py envia e atualiza o status."""
    validar_id(foto_id)
    destino = normalizar_whatsapp(whatsapp)
    if not destino:
        raise ValueError("número de WhatsApp inválido")
    pedido = {
        "foto": f"{foto_id}.jpg",
        "canal": "whatsapp",
        "destino": destino,
        "status": "pendente",
        "criado_em": datetime.now().isoformat(timespec="seconds"),
    }
    gravar(FILA / f"{foto_id}.json", json.dumps(pedido, ensure_ascii=False, indent=2).encode())


def status_envio(foto_id):
    try:
        pedido = json.loads((FILA / f"{validar_id(foto_id)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "inexistente"}
    return {"status": pedido["status"], "erro": pedido.get("erro")}


def status_whatsapp(verificar=False):
    """Painel do operador: configuração (sem o token), pausa, fila e, se pedido, a conta na API."""
    cfg = whatsapp.carregar()
    situacao = {**{k: v for k, v in cfg.items() if k != "token"}, "token_salvo": bool(cfg["token"]), "configurado": whatsapp.configurado(cfg)}
    if verificar and situacao["configurado"]:  # sob demanda: a Meta limita chamadas de gestão por hora
        try:
            situacao["conta"] = whatsapp.conta(cfg)
        except whatsapp.ErroWhatsApp as erro:
            situacao["erro_conta"] = str(erro)
    return {**situacao, "pausa": whatsapp.estado["pausa"], **whatsapp.resumo(FILA)}


class Cabine(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.permitido():
            return
        rota = urlsplit(self.path).path
        if rota == "/api/presets":
            return self.responder(200, [{"id": chave, "nome": nome} for chave, (nome, _) in tratamento.PRESETS.items()])
        if achado := re.fullmatch(r"/api/envios/([\w-]+)", rota):
            return self.responder(200, status_envio(achado[1]))
        if rota == "/api/whatsapp":
            return self.responder(200, status_whatsapp("verificar" in parse_qs(urlsplit(self.path).query)))
        if achado := re.fullmatch(r"/fotos/([\w-]+)\.jpg", rota):
            return self.arquivo(FOTOS / f"{achado[1]}.jpg" if ID_FOTO.fullmatch(achado[1]) else None)
        super().do_GET()

    def do_POST(self):
        if not self.permitido(post=True):
            return
        url = urlsplit(self.path)
        try:
            if url.path == "/api/moldura":
                salvar_moldura(self.ler_corpo())
                self.responder(201, {"ok": True})
            elif url.path == "/api/fotos":
                preset = parse_qs(url.query).get("preset", [None])[0]
                self.responder(201, {"id": salvar_foto(self.ler_corpo(), preset)})
            elif achado := re.fullmatch(r"/api/fotos/([\w-]+)/preset", url.path):
                tratar(achado[1], self.ler_json().get("preset"))
                self.responder(200, {"ok": True})
            elif url.path == "/api/envios":
                dados = self.ler_json()
                enfileirar_envio(dados.get("id"), dados.get("whatsapp"))
                self.responder(201, {"ok": True})
            elif url.path == "/api/whatsapp/config":
                whatsapp.salvar(self.ler_json())
                self.responder(200, status_whatsapp(verificar=True))
            elif url.path == "/api/whatsapp/teste":
                destino = normalizar_whatsapp(self.ler_json().get("numero"))
                if not destino:
                    raise ValueError("número de WhatsApp inválido")
                try:
                    self.responder(200, whatsapp.testar(destino, FOTOS))
                except whatsapp.ErroWhatsApp as erro:
                    self.responder(502, {"erro": str(erro)})
            elif url.path == "/api/whatsapp/reenviar":
                whatsapp.reenviar_erros(FILA)
                self.responder(200, status_whatsapp())
            else:
                self.responder(404, {"erro": "rota inexistente"})
        except ValueError as erro:  # inclui JSON malformado
            self.responder(400, {"erro": str(erro)})

    def permitido(self, post=False):
        """Só a própria cabine: bloqueia DNS rebinding (Host) e outros sites no mesmo navegador (Origin)."""
        host = self.headers.get("Host", "").rsplit(":", 1)[0]
        origem = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost") or (post and origem and urlsplit(origem).hostname not in ("127.0.0.1", "localhost")):
            self.responder(403, {"erro": "acesso permitido só pela própria cabine"})
            return False
        return True

    def ler_corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if not 0 < tamanho <= MAX_CORPO:
            raise ValueError("tamanho do envio inválido")
        return self.rfile.read(tamanho)

    def ler_json(self):
        dados = json.loads(self.ler_corpo())
        if not isinstance(dados, dict):
            raise ValueError("JSON inválido")
        return dados

    def arquivo(self, caminho):
        if not caminho or not caminho.exists():
            return self.responder(404, {"erro": "foto não encontrada"})
        corpo = caminho.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def responder(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # editou o config.json? basta recarregar
        super().end_headers()

    def log_message(self, formato, *args):
        # Vai para cabine.log, não para o console: no Windows, clicar na janela do console
        # pausa a escrita e travaria as requisições.
        log.info(formato, *args)


if __name__ == "__main__":
    logging.basicConfig(filename=RAIZ / "cabine.log", level=logging.INFO, format="%(asctime)s %(message)s")
    # Só 127.0.0.1: a cabine não fica exposta na rede do evento.
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), partial(Cabine, directory=WEB))
    whatsapp.iniciar(FILA, FOTOS)
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Cabine Mágica no ar em {url}  (Ctrl+C para encerrar; registros em cabine.log)")
    print(f"Painel do operador (WhatsApp, fila de envios): {url}/operador.html")
    if "--sem-navegador" not in sys.argv:  # no quiosque, quem abre o Chrome é o atalho de inicialização
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
