"""Envio oficial pelo WhatsApp: Cloud API da Meta ou parceiro oficial (BSP) com o mesmo formato.

- "meta": número registrado direto na Cloud API (token permanente de System User).
- "360dialog": número do app WhatsApp Business conectado por QR Code (coexistência) no
  painel do parceiro; a cabine só usa a chave de API gerada lá.

Uma thread lê fila/*.json "pendente", sobe a foto, manda o template aprovado com a foto no
cabeçalho e grava o resultado no próprio pedido. Configuração em whatsapp.json (fora de web/,
nunca vai para o navegador). Teste rápido:  python whatsapp.py 49999991234
"""
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parent
CONFIG = RAIZ / "whatsapp.json"
PADRAO = {"provedor": "meta", "token": "", "phone_number_id": "", "versao_api": "v26.0", "template": "foto_cabine_magica", "idioma": "pt_BR", "api_base": ""}
LIMITE_IMAGEM = 5_000_000  # Cloud API: imagem JPEG/PNG de até 5 MB

# Códigos oficiais (developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes)
REPETIR = {1, 2, 4, 80007, 130429, 131000, 131056, 131057}  # instabilidade/limite: tenta de novo com espera 4^n
PAUSAR = {0, 3, 10, 190, 200, 368, 131005, 131031, 131042, 132001, 132015, 132016, 133010}  # problema na conta/config
TRAVA = threading.Lock()
estado = {"pausa": None, "pausa_desde": 0.0}


class ErroWhatsApp(Exception):
    def __init__(self, codigo, mensagem, detalhes=None, http=None):
        super().__init__(f"{mensagem} (código {codigo})" + (f": {detalhes}" if detalhes else ""))
        self.codigo, self.http = codigo, http

    @property
    def tipo(self):
        if self.codigo is None or self.codigo in REPETIR or (self.http or 0) >= 500:
            return "repetir"
        return "pausar" if self.codigo in PAUSAR else "falhou"


def carregar():
    try:
        return {**PADRAO, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(PADRAO)


def salvar(novos):
    """Grava só as chaves conhecidas; token em branco mantém o atual."""
    cfg = carregar()
    for chave in PADRAO:
        valor = str(novos.get(chave, "")).strip()
        if valor or chave not in ("token", "api_base"):
            cfg[chave] = valor or PADRAO[chave]
    if cfg["provedor"] not in ("meta", "360dialog"):
        raise ValueError("provedor deve ser 'meta' ou '360dialog'")
    temporario = CONFIG.with_suffix(".tmp")
    temporario.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(CONFIG)
    estado["pausa"] = None  # configuração nova: volta a tentar


def configurado(cfg):
    return bool(cfg["token"] and cfg["template"] and (cfg["provedor"] != "meta" or cfg["phone_number_id"]))


def _endpoint(cfg, recurso):
    """URL e autenticação. api_base (opcional) aponta para outro parceiro compatível com a Cloud API."""
    if cfg["provedor"] == "360dialog":
        return f"{cfg['api_base'] or 'https://waba-v2.360dialog.io'}/{recurso}", {"D360-API-KEY": cfg["token"]}
    base = cfg["api_base"] or f"https://graph.facebook.com/{cfg['versao_api']}"
    return f"{base}/{cfg['phone_number_id']}/{recurso}".rstrip("/"), {"Authorization": f"Bearer {cfg['token']}"}


def _chamar(cfg, recurso, corpo=None, tipo="application/json", metodo="POST"):
    url, cabecalhos = _endpoint(cfg, recurso)
    req = urllib.request.Request(url, data=corpo, method=metodo, headers={**cabecalhos, "Content-Type": tipo})
    try:
        with urllib.request.urlopen(req, timeout=40) as resposta:
            return json.load(resposta)
    except urllib.error.HTTPError as erro:
        try:
            info = json.load(erro).get("error", {})
        except ValueError:
            info = {}
        raise ErroWhatsApp(info.get("code", erro.code), info.get("message", erro.reason), (info.get("error_data") or {}).get("details"), erro.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as erro:  # sem internet: tenta de novo depois
        raise ErroWhatsApp(None, f"sem conexão com o WhatsApp ({erro})") from None


def jpeg_para_envio(dados):
    """Garante o limite de 5 MB reduzindo resolução/qualidade só da cópia enviada."""
    if len(dados) <= LIMITE_IMAGEM:
        return dados
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    escala = min(1.0, 3840 / max(img.shape[:2]))
    img = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    for qualidade in (90, 84, 78, 70, 60):
        dados = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])[1].tobytes()
        if len(dados) <= LIMITE_IMAGEM:
            return dados
    return dados


def subir_foto(cfg, jpeg):
    limite = secrets.token_hex(16)
    partes = [f'--{limite}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n{valor}\r\n'.encode() for nome, valor in (("messaging_product", "whatsapp"), ("type", "image/jpeg"))]
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="foto.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + jpeg + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return _chamar(cfg, "media", b"".join(partes), f"multipart/form-data; boundary={limite}")["id"]


def enviar_template(cfg, destino, media_id):
    """Template aprovado com a foto no cabeçalho: único tipo permitido para quem nunca escreveu à empresa."""
    corpo = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": destino,
        "type": "template",
        "template": {
            "name": cfg["template"],
            "language": {"code": cfg["idioma"]},
            "components": [{"type": "header", "parameters": [{"type": "image", "image": {"id": media_id}}]}],
        },
    }
    resposta = _chamar(cfg, "messages", json.dumps(corpo).encode())
    return resposta["messages"][0]["id"], (resposta.get("contacts") or [{}])[0].get("wa_id")


def conta(cfg):
    """Número e nome verificados (só na Cloud API direta; o parceiro não expõe essa rota)."""
    if cfg["provedor"] != "meta":
        return None
    url, cabecalhos = _endpoint(cfg, "")
    req = urllib.request.Request(f"{url}?fields=display_phone_number,verified_name,quality_rating", headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=15) as resposta:
            return json.load(resposta)
    except urllib.error.HTTPError as erro:
        try:
            info = json.load(erro).get("error", {})
        except ValueError:
            info = {}
        raise ErroWhatsApp(info.get("code", erro.code), info.get("message", erro.reason), http=erro.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ErroWhatsApp(None, f"sem conexão com o WhatsApp ({erro})") from None


def _ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def _gravar(caminho, pedido):
    temporario = caminho.with_name(f".{caminho.name}.{secrets.token_hex(4)}.tmp")
    temporario.write_text(json.dumps(pedido, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def processar(caminho, fotos, cfg):
    """Envia um pedido da fila. Devolve False se a fila deve pausar (problema na conta)."""
    with TRAVA:
        pedido = _ler(caminho)
    if pedido.get("status") != "pendente" or pedido.get("proxima_tentativa", "") > datetime.now().isoformat():
        return True
    try:
        if not pedido.get("media_id") or pedido.get("media_em", "") < (datetime.now() - timedelta(days=29)).isoformat():
            pedido["media_id"] = subir_foto(cfg, jpeg_para_envio((fotos / pedido["foto"]).read_bytes()))  # vale 30 dias
            pedido["media_em"] = datetime.now().isoformat(timespec="seconds")
        pedido["wamid"], pedido["wa_id"] = enviar_template(cfg, pedido["destino"], pedido["media_id"])
        pedido.update(status="enviado", enviado_em=datetime.now().isoformat(timespec="seconds"), erro=None)
    except ErroWhatsApp as erro:
        pedido["erro"] = str(erro)
        if erro.tipo == "pausar":
            estado.update(pausa=str(erro), pausa_desde=time.time())
        elif erro.tipo == "repetir":
            pedido["tentativas"] = pedido.get("tentativas", 0) + 1
            espera = min(4 ** pedido["tentativas"], 900)  # 4, 16, 64… até 15 min (recomendação da Meta)
            pedido["proxima_tentativa"] = (datetime.now() + timedelta(seconds=espera)).isoformat(timespec="seconds")
        else:
            pedido["status"] = "erro"  # sem WhatsApp, número inválido…: o operador decide reenviar
    except OSError as erro:
        pedido.update(status="erro", erro=f"foto não encontrada ({erro})")
    with TRAVA:
        _gravar(caminho, pedido)
    return estado["pausa"] is None


def trabalhar(fila, fotos):
    while True:
        cfg = carregar()
        # Conta com problema: espera o operador salvar a configuração (zera a pausa) ou 10 min.
        if estado["pausa"] and time.time() - estado["pausa_desde"] > 600:
            estado["pausa"] = None
        if configurado(cfg) and not estado["pausa"]:
            for caminho in sorted(fila.glob("*.json")):
                if not processar(caminho, fotos, cfg):
                    break
        time.sleep(2)


def resumo(fila):
    contagem = {"pendente": 0, "enviado": 0, "erro": 0}
    erros = []
    for caminho in sorted(fila.glob("*.json"), reverse=True):
        try:
            pedido = _ler(caminho)
        except (OSError, ValueError):
            continue
        contagem[pedido.get("status", "pendente")] = contagem.get(pedido.get("status", "pendente"), 0) + 1
        if pedido.get("erro") and len(erros) < 10:
            erros.append({"id": caminho.stem, "destino": pedido["destino"], "status": pedido["status"], "erro": pedido["erro"]})
    return {"fila": contagem, "erros": erros}


def reenviar_erros(fila):
    with TRAVA:
        for caminho in fila.glob("*.json"):
            pedido = _ler(caminho)
            if pedido.get("status") == "erro":
                pedido.update(status="pendente", tentativas=0, proxima_tentativa="", erro=None)
                _gravar(caminho, pedido)
    estado["pausa"] = None


def testar(destino, fotos):
    """Envia agora (sem fila) a foto mais recente, ou uma imagem de teste: valida conta, token e template."""
    cfg = carregar()
    if not configurado(cfg):
        raise ErroWhatsApp("config", "preencha o token, o template e (na Meta) o phone_number_id")
    recentes = sorted(fotos.glob("*.jpg"))
    if recentes:
        jpeg = recentes[-1].read_bytes()
    else:
        img = np.full((1080, 1920, 3), (147, 65, 22), np.uint8)  # azul SENAI (BGR)
        cv2.putText(img, "Teste da Cabine Magica", (420, 560), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 6)
        jpeg = cv2.imencode(".jpg", img)[1].tobytes()
    wamid, wa_id = enviar_template(cfg, destino, subir_foto(cfg, jpeg_para_envio(jpeg)))
    return {"wamid": wamid, "wa_id": wa_id}


def iniciar(fila, fotos):
    threading.Thread(target=trabalhar, args=(fila, fotos), daemon=True, name="whatsapp").start()


if __name__ == "__main__":
    import sys

    # Auto-teste offline da classificação de erros e do limite de 5 MB.
    assert ErroWhatsApp(131056, "pair rate").tipo == "repetir"
    assert ErroWhatsApp(None, "sem internet").tipo == "repetir"
    assert ErroWhatsApp(190, "token expirado").tipo == "pausar"
    assert ErroWhatsApp(131026, "sem WhatsApp").tipo == "falhou"
    assert ErroWhatsApp(999999, "desconhecido", http=503).tipo == "repetir"
    ruido = np.random.default_rng(0).integers(0, 255, (3000, 4000, 3), np.uint8)
    assert len(jpeg_para_envio(cv2.imencode(".jpg", ruido, [cv2.IMWRITE_JPEG_QUALITY, 100])[1].tobytes())) <= LIMITE_IMAGEM
    print("auto-teste ok")
    if len(sys.argv) > 1:  # envio real: python whatsapp.py 49999991234  (DDD + número, sem o 55)
        print(testar("55" + "".join(c for c in sys.argv[1] if c.isascii() and c.isdigit()), RAIZ / "fotos"))
