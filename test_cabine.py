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

servidor.shutdown()
print("ok")
