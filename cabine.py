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

import segno

import celular
import compartilhar
import tratamento
import whatsapp
from whatsapp import gravar

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
FOTOS = RAIZ / "fotos"
ORIGINAIS = FOTOS / "originais"
MOLDURAS = RAIZ / "molduras"
FILA = RAIZ / "fila"
EVENTO = RAIZ / "evento.json"
PORTA = 8765
MAX_CORPO = 60 * 1024 * 1024
ID_FOTO = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
PNG = b"\x89PNG\r\n\x1a\n"
FORMATOS = ("story", "feed", "quadrado", "grande")
RESOLUCOES = ("max", "3840x2160", "2560x1440", "1920x1080", "1280x720")
log = logging.getLogger("cabine")


def _texto(valor):
    return isinstance(valor, str) and len(valor) <= 60


def _cor(valor):
    return isinstance(valor, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", valor) is not None


def _imagem(valor):
    return valor == "" or isinstance(valor, str) and re.fullmatch(r"(evento/)?[\w-]+\.png", valor, re.ASCII) is not None and (WEB / valor).is_file()


def _logico(valor):
    return isinstance(valor, bool)


def _opcao(opcoes):
    return lambda valor: isinstance(valor, str) and valor in opcoes


def _lista(opcoes):
    return lambda valor: isinstance(valor, list) and len(valor) > 0 and all(isinstance(item, str) and item in opcoes for item in valor)


def _inteiro(minimo, maximo):
    return lambda valor: type(valor) is int and minimo <= valor <= maximo


CAMPOS = {
    "titulo": ("MUNDO SENAI 2026", _texto),
    "unidade": ("SENAI FRAIBURGO", _texto),
    "hashtag": ("#EU_FUI!", _texto),
    "cor_primaria": ("#164193", _cor),
    "cor_destaque": ("#E84910", _cor),
    "logo": ("logo-senai-branco.png", _imagem),
    "moldura_png": ("", _imagem),
    "formatos": (list(FORMATOS), _lista(FORMATOS)),
    "formato": ("feed", _opcao(FORMATOS)),
    "presets": (list(tratamento.PRESETS), _lista(tratamento.PRESETS)),
    "preset": ("natural", _opcao(tratamento.PRESETS)),
    "whatsapp": (True, _logico),
    "qr_download": (True, _logico),
    "espelhar_previa": (True, _logico),
    "espelhar_foto": (True, _logico),
    "contagem": (3, _inteiro(0, 10)),
    "resolucao": ("max", _opcao(RESOLUCOES)),
    "fps": (30, _inteiro(10, 60)),
    "qualidade_jpeg": (0.92, lambda valor: type(valor) in (int, float) and 0.5 <= valor <= 1),
}


def evento():
    try:
        salvo = json.loads(EVENTO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        salvo = {}
    if not isinstance(salvo, dict):
        salvo = {}
    return {chave: salvo[chave] if chave in salvo and valido(salvo[chave]) else padrao for chave, (padrao, valido) in CAMPOS.items()}


def salvar_evento(novos):
    cfg = {**evento(), **{chave: valor for chave, valor in novos.items() if chave in CAMPOS}}
    invalidos = [chave for chave, (_, valido) in CAMPOS.items() if not valido(cfg[chave])]
    if invalidos:
        raise ValueError(f"valor inválido em: {', '.join(invalidos)}")
    if cfg["formato"] not in cfg["formatos"] or cfg["preset"] not in cfg["presets"]:
        raise ValueError("o formato e o ajuste iniciais precisam estar habilitados")
    gravar(EVENTO, json.dumps(cfg, ensure_ascii=False, indent=2).encode())
    return cfg


def nome_evento(cfg):
    return " · ".join(filter(None, (cfg["titulo"], cfg["unidade"])))


def salvar_imagem(campo, png):
    if campo not in ("logo", "moldura_png"):
        raise ValueError("campo de imagem inválido")
    if png[:8] != PNG:
        raise ValueError("a imagem precisa ser PNG")
    if campo == "moldura_png" and not transparente(png):
        raise ValueError("a moldura precisa ser PNG com transparência")
    nome = f"evento/{campo.removesuffix('_png')}-{secrets.token_hex(4)}.png"
    gravar(WEB / nome, png)
    return nome


def validar_id(foto_id):
    if not ID_FOTO.fullmatch(str(foto_id)) or not (ORIGINAIS / f"{foto_id}.jpg").exists():
        raise ValueError("foto não encontrada")
    return foto_id


def normalizar_whatsapp(numero):
    digitos = re.sub(r"\D", "", str(numero), flags=re.ASCII)
    return "55" + digitos if re.fullmatch(r"[1-9]{2}9[0-9]{8}", digitos) else None


def transparente(png):
    return png[:8] == PNG and len(png) > 25 and png[25] == 6


def salvar_moldura(png):
    if not transparente(png):
        raise ValueError("a moldura precisa ser PNG com transparência")
    largura, altura = struct.unpack(">II", png[16:24])
    gravar(MOLDURAS / f"{largura}x{altura}.png", png)


def tratar(foto_id, preset=None):
    cfg = evento()
    preset = preset or cfg["preset"]
    if preset not in tratamento.PRESETS:
        raise ValueError(f"ajuste desconhecido: {preset}")
    original = (ORIGINAIS / f"{validar_id(foto_id)}.jpg").read_bytes()
    qualidade = round(cfg["qualidade_jpeg"] * 100)
    try:
        final = tratamento.processar(original, preset, MOLDURAS, qualidade)
    except Exception:
        log.exception("tratamento %s falhou em %s", preset, foto_id)
        final = tratamento.processar(original, "original", MOLDURAS, qualidade)
    gravar(FOTOS / f"{foto_id}.jpg", final)


def salvar_foto(jpeg, preset=None):
    if not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("a foto precisa ser JPEG")
    foto_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    gravar(ORIGINAIS / f"{foto_id}.jpg", jpeg)
    tratar(foto_id, preset)
    return foto_id


def enfileirar_envio(foto_id, numero):
    validar_id(foto_id)
    cfg = evento()
    if not cfg["whatsapp"]:
        raise ValueError("o envio por WhatsApp está desligado no painel do operador")
    destino = normalizar_whatsapp(numero)
    if not destino:
        raise ValueError("número de WhatsApp inválido")
    pedido = {
        "foto": f"{foto_id}.jpg",
        "canal": "whatsapp",
        "destino": destino,
        "status": "pendente",
        "evento": nome_evento(cfg),
        "criado_em": datetime.now().isoformat(timespec="seconds"),
    }
    gravar(FILA / f"{foto_id}.json", json.dumps(pedido, ensure_ascii=False, indent=2).encode())


def status_envio(foto_id):
    try:
        pedido = json.loads((FILA / f"{validar_id(foto_id)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "inexistente"}
    return {"status": pedido["status"], "erro": pedido.get("erro")}


def svg_qr(texto, correcao):
    return segno.make(texto, error=correcao).svg_inline(border=4, dark="#000000", light="#ffffff", omitsize=True)


def link_download(foto_id):
    validar_id(foto_id)
    url = compartilhar.link(foto_id) if evento()["qr_download"] else None
    qr = svg_qr(url, "m") if url else None
    return {"url": url, "qr": qr, "erro": compartilhar.estado["erro"]}


def status_whatsapp(verificar=False):
    cfg = whatsapp.carregar()
    situacao = {**{k: v for k, v in cfg.items() if k != "token"}, "token_salvo": bool(cfg["token"]), "configurado": whatsapp.configurado(cfg)}
    if verificar and situacao["configurado"]:
        try:
            situacao["conta"] = whatsapp.conta(cfg)
        except whatsapp.ErroWhatsApp as erro:
            situacao["erro_conta"] = str(erro)
    if cfg["provedor"] == "celular":
        estado = celular.estado
        qr = svg_qr(estado["qr"], "l") if estado["qr"] else None
        situacao["celular"] = {**{k: v for k, v in estado.items() if k != "qr"}, "qr": qr}
    return {**situacao, "pausa": whatsapp.estado["pausa"], **whatsapp.resumo(FILA)}


class Cabine(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.permitido():
            return
        rota = urlsplit(self.path).path
        if rota == "/api/evento":
            return self.responder(200, evento())
        if rota == "/api/presets":
            return self.responder(200, [{"id": chave, "nome": nome} for chave, (nome, _) in tratamento.PRESETS.items()])
        if achado := re.fullmatch(r"/api/envios/([\w-]+)", rota):
            return self.responder(200, status_envio(achado[1]))
        if achado := re.fullmatch(r"/api/fotos/([\w-]+)/link", rota):
            return self.responder(200, link_download(achado[1]))
        if rota == "/api/whatsapp":
            return self.responder(200, status_whatsapp("verificar" in urlsplit(self.path).query))
        if achado := re.fullmatch(r"/fotos/([\w-]+)\.jpg", rota):
            return self.arquivo(FOTOS / f"{achado[1]}.jpg" if ID_FOTO.fullmatch(achado[1]) else None)
        super().do_GET()

    def do_POST(self):
        if not self.permitido(post=True):
            return
        url = urlsplit(self.path)
        try:
            if url.path == "/api/evento":
                self.responder(200, salvar_evento(self.ler_json()))
            elif url.path == "/api/evento/imagem":
                campo = parse_qs(url.query).get("campo", [""])[0]
                self.responder(201, {"caminho": salvar_imagem(campo, self.ler_corpo())})
            elif url.path == "/api/moldura":
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
                    self.responder(200, whatsapp.testar(destino, FOTOS, nome_evento(evento())))
                except whatsapp.ErroWhatsApp as erro:
                    self.responder(502, {"erro": str(erro)})
            elif url.path == "/api/whatsapp/celular/conectar":
                celular.iniciar()
                self.responder(200, status_whatsapp())
            elif url.path == "/api/whatsapp/celular/desconectar":
                celular.desconectar()
                self.responder(200, status_whatsapp())
            elif url.path == "/api/whatsapp/reenviar":
                whatsapp.reenviar_erros(FILA)
                self.responder(200, status_whatsapp())
            else:
                self.responder(404, {"erro": "rota inexistente"})
        except ValueError as erro:
            self.responder(400, {"erro": str(erro)})

    def permitido(self, post=False):
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
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, formato, *args):
        log.info(formato, *args)


if __name__ == "__main__":
    logging.basicConfig(filename=RAIZ / "cabine.log", level=logging.INFO, format="%(asctime)s %(message)s")
    ThreadingHTTPServer.allow_reuse_address = sys.platform != "win32"
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), partial(Cabine, directory=WEB))
    whatsapp.iniciar(FILA, FOTOS)
    if whatsapp.carregar()["provedor"] == "celular" and celular.SESSAO.exists():
        celular.iniciar()
    compartilhar.iniciar(FOTOS)
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Cabine Mágica no ar em {url}  (Ctrl+C para encerrar; registros em cabine.log)")
    print(f"Painel do operador (WhatsApp, fila de envios): {url}/operador.html")
    if "--sem-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
