"""Auto-teste do servidor: python test_cabine.py"""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

import cabine

assert cabine.normalizar_whatsapp("(49) 99999-1234") == "5549999991234"
assert cabine.normalizar_whatsapp("4999991234") is None  # sem o 9
assert cabine.normalizar_whatsapp("(09) 99999-1234") is None  # DDD inválido
assert cabine.normalizar_whatsapp("٤٩٩٩٩٩٩١٢٣٤") is None  # dígitos não ASCII
assert cabine.normalizar_whatsapp(None) is None

tmp = Path(tempfile.mkdtemp())
cabine.FOTOS, cabine.ORIGINAIS, cabine.MOLDURAS, cabine.FILA = tmp / "fotos", tmp / "fotos/originais", tmp / "molduras", tmp / "fila"
servidor = ThreadingHTTPServer(("127.0.0.1", 0), partial(cabine.Cabine, directory=cabine.WEB))
threading.Thread(target=servidor.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{servidor.server_port}"


def pedir(rota, corpo=None, tipo="application/json", **cabecalhos):
    req = urllib.request.Request(base + rota, data=corpo, headers={"Content-Type": tipo, **cabecalhos})
    try:
        with urllib.request.urlopen(req) as r:
            dados = r.read()
            return r.status, json.loads(dados) if r.headers.get_content_type() == "application/json" else dados
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


cena = np.full((48, 64, 3), (40, 60, 120), np.uint8)  # escura e quente
jpeg = cv2.imencode(".jpg", cena)[1].tobytes()
moldura = np.zeros((48, 64, 4), np.uint8)
moldura[40:] = (255, 0, 0, 255)  # faixa azul opaca embaixo
png = cv2.imencode(".png", moldura)[1].tobytes()

# Só a própria cabine pode chamar a API
assert pedir("/api/fotos", jpeg, "image/jpeg", Origin="https://site-qualquer.com")[0] == 403
assert pedir("/api/presets", Host="cabine.atacante.com")[0] == 403

assert pedir("/api/moldura", jpeg, "image/png")[0] == 400
assert pedir("/api/moldura", png, "image/png", Origin="http://127.0.0.1:8765")[0] == 201
assert (cabine.MOLDURAS / "64x48.png").exists()

status, dados = pedir("/api/fotos?preset=natural", jpeg, "image/jpeg")
assert status == 201, dados
foto_id = dados["id"]
assert (cabine.ORIGINAIS / f"{foto_id}.jpg").exists()
status, final = pedir(f"/fotos/{foto_id}.jpg?v=1")
final = cv2.imdecode(np.frombuffer(final, np.uint8), 1)
assert status == 200 and final.shape == cena.shape
assert final[44, 32, 0] > 200 and final[44, 32, 2] < 60, "moldura não foi aplicada"
assert final[:30].mean() > cena.mean(), "preset natural não clareou a cena escura"

assert pedir(f"/api/fotos/{foto_id}/preset", b'{"preset": "pb"}')[0] == 200
b, g, r = cv2.split(cv2.imdecode(np.frombuffer(pedir(f"/fotos/{foto_id}.jpg")[1], np.uint8), 1)[:30].astype(int))
assert abs(b - r).max() < 12, "P&B deveria sair sem cor"
assert pedir(f"/api/fotos/{foto_id}/preset", b'{"preset": "neon"}')[0] == 400
assert "natural" in [p["id"] for p in pedir("/api/presets")[1]]

assert pedir("/api/fotos", b"nao-e-jpeg", "image/jpeg")[0] == 400
assert pedir("/api/envios", json.dumps({"id": "../cabine", "whatsapp": "49999991234"}).encode())[0] == 400
assert pedir("/api/envios", json.dumps({"id": foto_id, "whatsapp": "123"}).encode())[0] == 400
assert pedir("/api/envios", b"[1, 2]")[0] == 400
assert pedir("/api/envios", b"{quebrado")[0] == 400
assert pedir("/api/nada", b"{}")[0] == 404
assert pedir(f"/api/envios/{foto_id}")[1]["status"] == "inexistente"

assert pedir("/api/envios", json.dumps({"id": foto_id, "whatsapp": "(49) 99999-1234"}).encode())[0] == 201
pedido = json.loads((cabine.FILA / f"{foto_id}.json").read_text(encoding="utf-8"))
assert pedido["destino"] == "5549999991234" and pedido["status"] == "pendente" and pedido["foto"] == f"{foto_id}.jpg"
assert pedir(f"/api/envios/{foto_id}")[1]["status"] == "pendente"

assert "hashtag" in pedir("/config.json")[1]

# ---------- Download pelo celular: servidor público separado, links assinados ----------
import compartilhar  # noqa: E402

compartilhar.SEGREDO = tmp / "segredo.key"
assert pedir(f"/api/fotos/{foto_id}/link")[1]["url"] is None  # sem túnel: sem QR
compartilhar.Publico.fotos = cabine.FOTOS
publico = ThreadingHTTPServer(("127.0.0.1", 0), compartilhar.Publico)
threading.Thread(target=publico.serve_forever, daemon=True).start()
compartilhar.estado["url"] = f"http://127.0.0.1:{publico.server_port}"
info = pedir(f"/api/fotos/{foto_id}/link")[1]
assert info["url"].endswith(f"/f/{foto_id}/{compartilhar.assinatura(foto_id)}") and info["qr"].startswith("<svg")
with urllib.request.urlopen(info["url"]) as r:
    assert b"foto.jpg" in r.read()
with urllib.request.urlopen(info["url"] + "/foto.jpg?baixar=1") as r:
    assert r.headers["Content-Disposition"].startswith("attachment") and r.read() == (cabine.FOTOS / f"{foto_id}.jpg").read_bytes()
for ruim in (f"/f/{foto_id}/AAAAAAAAAAAAAAAA", f"/f/{foto_id}", "/api/presets", "/config.json", f"/f/../{foto_id}/x"):
    try:
        urllib.request.urlopen(compartilhar.estado["url"] + ruim)
        raise AssertionError(f"servidor público respondeu {ruim}")
    except urllib.error.HTTPError as e:
        assert e.code == 404, ruim
publico.shutdown()
compartilhar.estado["url"] = None

# ---------- WhatsApp: worker contra uma API falsa no formato da Cloud API ----------
import whatsapp  # noqa: E402
from http.server import BaseHTTPRequestHandler  # noqa: E402

RESPOSTAS = {  # destino → (http, corpo)
    "5549999990001": (200, {"messages": [{"id": "wamid.OK"}], "contacts": [{"wa_id": "5549999990001"}]}),
    "5549999990002": (400, {"error": {"code": 131026, "message": "Message undeliverable"}}),
    "5549999990003": (400, {"error": {"code": 131056, "message": "pair rate limit"}}),
    "5549999990004": (401, {"error": {"code": 190, "message": "token expirado"}}),
}
recebidos = []


class ApiFalsa(BaseHTTPRequestHandler):
    def do_POST(self):
        corpo = self.rfile.read(int(self.headers["Content-Length"]))
        assert self.headers["D360-API-KEY"] == "CHAVE"
        if self.path == "/media":
            assert b"image/jpeg" in corpo and b"\xff\xd8" in corpo
            status, dados = 200, {"id": "MEDIA1"}
        else:
            msg = json.loads(corpo)
            recebidos.append(msg)
            assert msg["template"]["components"][0]["parameters"][0]["image"]["id"] == "MEDIA1"
            status, dados = RESPOSTAS[msg["to"]]
        saida = json.dumps(dados).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(saida)))
        self.end_headers()
        self.wfile.write(saida)

    def log_message(self, *args):
        pass


api = ThreadingHTTPServer(("127.0.0.1", 0), ApiFalsa)
threading.Thread(target=api.serve_forever, daemon=True).start()
whatsapp.CONFIG = tmp / "whatsapp.json"
assert pedir("/api/whatsapp")[1]["configurado"] is False
assert pedir("/api/whatsapp/teste", b'{"numero": "49999990001"}')[0] == 502  # sem configuração
assert pedir("/api/whatsapp/config", b'{"provedor": "pombo-correio"}')[0] == 400
whatsapp.salvar({"provedor": "360dialog", "token": "CHAVE", "template": "foto_cabine_magica", "idioma": "pt_BR", "api_base": f"http://127.0.0.1:{api.server_port}"})
status = pedir("/api/whatsapp")[1]
assert status["configurado"] and status["token_salvo"] and "CHAVE" not in json.dumps(status), "token vazou para o navegador"

cfg = whatsapp.carregar()
for final in "1234":
    caminho = cabine.FILA / f"teste-{final}.json"
    caminho.write_text(json.dumps({**pedido, "destino": f"554999999000{final}"}), encoding="utf-8")
    continuar = whatsapp.processar(caminho, cabine.FOTOS, cfg)
    resultado = json.loads(caminho.read_text(encoding="utf-8"))
    if final == "1":
        assert resultado["status"] == "enviado" and resultado["wamid"] == "wamid.OK" and resultado["media_id"] == "MEDIA1"
    if final == "2":
        assert resultado["status"] == "erro" and "131026" in resultado["erro"]
    if final == "3":
        assert resultado["status"] == "pendente" and resultado["tentativas"] == 1 and resultado["proxima_tentativa"]
    if final == "4":
        assert not continuar and whatsapp.estado["pausa"] and resultado["status"] == "pendente", "token inválido deve pausar a fila"
assert recebidos[0]["template"]["language"]["code"] == "pt_BR"
assert pedir("/api/whatsapp")[1]["fila"]["erro"] == 1
assert pedir("/api/whatsapp/reenviar", b"{}")[1]["fila"]["erro"] == 0
assert whatsapp.estado["pausa"] is None
api.shutdown()

# ---------- Modo celular (grátis): worker com o envio do celular simulado ----------
import celular  # noqa: E402

enviados = []


def envio_falso(destino, jpeg, nome):
    if destino.endswith("0002"):
        raise celular.ErroCelular("este número não tem WhatsApp", repetir=False)
    if destino.endswith("0003"):
        raise celular.ErroCelular("falha ao enviar: rede", repetir=True)
    enviados.append((destino, len(jpeg), nome))
    return "MSGID"


celular.enviar, celular.iniciar = envio_falso, lambda: None
whatsapp.salvar({"provedor": "celular"})
cfg = whatsapp.carregar()
assert not whatsapp.configurado(cfg), "celular desconectado não pode contar como configurado"
assert pedir("/api/whatsapp")[1]["celular"]["status"] == "desligado"
celular.estado.update(status="conectado", numero="5549988887777")
assert whatsapp.configurado(cfg)
for final in "123":
    caminho = cabine.FILA / f"celular-{final}.json"
    caminho.write_text(json.dumps({**pedido, "destino": f"554999999000{final}"}), encoding="utf-8")
    whatsapp.processar(caminho, cabine.FOTOS, cfg)
    resultado = json.loads(caminho.read_text(encoding="utf-8"))
    esperado = {"1": "enviado", "2": "erro", "3": "pendente"}[final]
    assert resultado["status"] == esperado, (final, resultado)
assert enviados == [("5549999990001", len((cabine.FOTOS / pedido["foto"]).read_bytes()), f"cabine-magica-{pedido['foto']}")]
assert json.loads((cabine.FILA / "celular-3.json").read_text(encoding="utf-8"))["tentativas"] == 1
assert pedir("/api/whatsapp/teste", b'{"numero": "49999990001"}')[1]["wamid"] == "MSGID"
assert pedir("/api/whatsapp/celular/desconectar", b"{}")[1]["celular"]["status"] == "desligado"

servidor.shutdown()
print("ok")
