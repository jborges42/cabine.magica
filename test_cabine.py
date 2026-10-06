"""Auto-teste do servidor: python3 test_cabine.py"""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import cabine

assert cabine.normalizar_whatsapp("(49) 99999-1234") == "5549999991234"
assert cabine.normalizar_whatsapp("4999991234") is None  # sem o 9
assert cabine.normalizar_whatsapp("(09) 99999-1234") is None  # DDD inválido
assert cabine.normalizar_whatsapp(None) is None

tmp = Path(tempfile.mkdtemp())
cabine.FOTOS, cabine.FILA = tmp / "fotos", tmp / "fila"
servidor = ThreadingHTTPServer(("127.0.0.1", 0), partial(cabine.Cabine, directory=cabine.RAIZ / "web"))
threading.Thread(target=servidor.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{servidor.server_port}"


def post(rota, corpo, tipo="application/json"):
    req = urllib.request.Request(base + rota, data=corpo, headers={"Content-Type": tipo})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


status, dados = post("/api/fotos", b"\xff\xd8 jpeg falso", "image/jpeg")
assert status == 201 and (cabine.FOTOS / f"{dados['id']}.jpg").exists(), dados
foto_id = dados["id"]

assert post("/api/fotos", b"nao-e-jpeg", "image/jpeg")[0] == 400
assert post("/api/envios", json.dumps({"id": "../cabine", "whatsapp": "49999991234"}).encode())[0] == 400
assert post("/api/envios", json.dumps({"id": foto_id, "whatsapp": "123"}).encode())[0] == 400
assert post("/api/envios", b"[1, 2]")[0] == 400
assert post("/api/envios", b"{quebrado")[0] == 400
assert post("/api/nada", b"{}")[0] == 404

assert post("/api/envios", json.dumps({"id": foto_id, "whatsapp": "(49) 99999-1234"}).encode())[0] == 201
pedido = json.loads((cabine.FILA / f"{foto_id}.json").read_text(encoding="utf-8"))
assert pedido["destino"] == "5549999991234" and pedido["status"] == "pendente" and pedido["foto"] == f"{foto_id}.jpg"

with urllib.request.urlopen(base + "/config.json") as r:
    assert json.load(r)["hashtag"] == "#EU_FUI!"

servidor.shutdown()
print("ok")
