"""Cabine Mágica — SENAI Fraiburgo.

Servidor local (só biblioteca padrão): entrega a interface de web/, salva as fotos
em fotos/ e registra os pedidos de envio em fila/ para as integrações futuras
(WhatsApp, e-mail). Rode com:  python3 cabine.py
"""
import json
import re
import secrets
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FOTOS = RAIZ / "fotos"
FILA = RAIZ / "fila"
PORTA = 8765
MAX_CORPO = 25 * 1024 * 1024
ID_FOTO = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")


def normalizar_whatsapp(numero):
    """Celular brasileiro (DDD + 9 + 8 dígitos) -> '55DD9XXXXXXXX'; inválido -> None."""
    digitos = re.sub(r"\D", "", str(numero))
    return "55" + digitos if re.fullmatch(r"[1-9]{2}9\d{8}", digitos) else None


def salvar_foto(jpeg):
    if not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("a foto precisa ser JPEG")
    foto_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    FOTOS.mkdir(exist_ok=True)
    (FOTOS / f"{foto_id}.jpg").write_bytes(jpeg)
    return foto_id


def enfileirar_envio(foto_id, whatsapp):
    """Cria fila/<id>.json com status 'pendente'. As integrações leem a fila,
    enviam a foto e atualizam o status — a cabine não espera por elas."""
    if not ID_FOTO.fullmatch(str(foto_id)) or not (FOTOS / f"{foto_id}.jpg").exists():
        raise ValueError("foto não encontrada")
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
    FILA.mkdir(exist_ok=True)
    temporario = FILA / f"{foto_id}.tmp"
    temporario.write_text(json.dumps(pedido, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(FILA / f"{foto_id}.json")  # atômico: o leitor nunca vê arquivo pela metade


class Cabine(SimpleHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path == "/api/fotos":
                self.responder(201, {"id": salvar_foto(self.ler_corpo())})
            elif self.path == "/api/envios":
                dados = json.loads(self.ler_corpo())
                if not isinstance(dados, dict):
                    raise ValueError("JSON inválido")
                enfileirar_envio(dados.get("id"), dados.get("whatsapp"))
                self.responder(201, {"ok": True})
            else:
                self.responder(404, {"erro": "rota inexistente"})
        except ValueError as erro:  # inclui JSON malformado
            self.responder(400, {"erro": str(erro)})

    def ler_corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if not 0 < tamanho <= MAX_CORPO:
            raise ValueError("tamanho do envio inválido")
        return self.rfile.read(tamanho)

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


if __name__ == "__main__":
    # Só 127.0.0.1: a cabine não fica exposta na rede do evento.
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), partial(Cabine, directory=RAIZ / "web"))
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Cabine Mágica no ar em {url}  (Ctrl+C para encerrar)")
    webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
