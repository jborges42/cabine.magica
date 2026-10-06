import atexit
import multiprocessing
import multiprocessing.connection
import os
import queue
import random
import re
import secrets
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SESSAO = RAIZ / "whatsapp-celular.sqlite3"
INTERVALO = (8.0, 20.0)
QR_VALIDADE = 75
LEGENDAS = (
    "Olá! Aqui está a sua foto da Cabine Mágica 📸 {evento}. Obrigado pela visita! Responda com um 👍 se recebeu.",
    "Oi! Sua foto da Cabine Mágica chegou 😄 {evento}. Manda um 👍 pra gente saber que deu certo.",
    "Prontinho! Essa é a sua foto da Cabine Mágica ✨ {evento}. Se puder, responda com um 👍 confirmando o recebimento.",
)
RESTRICAO = "O WhatsApp recusou a mensagem para um número novo (erro 463, restrição de contato). Envios pausados: não escaneie o QR de novo; espere a restrição acabar e clique em Reconectar."
estado = {"status": "desligado", "qr": None, "numero": None, "erro": None}
_contexto = multiprocessing.get_context("spawn")
_processo = [None]
_filas = {}
_pendentes = {}
_trava = threading.Lock()
_ultimo = {"envio": 0.0, "visto": 0.0}
atexit.register(lambda: _processo[0] and _processo[0].kill())


class ErroCelular(Exception):
    def __init__(self, mensagem, repetir):
        super().__init__(mensagem)
        self.repetir = repetir


def _filho(sessao, pedidos, eventos):
    pai = multiprocessing.parent_process()
    threading.Thread(target=lambda: (multiprocessing.connection.wait([pai.sentinel]), os._exit(0)), daemon=True).start()
    from neonize.client import NewClient
    from neonize.events import ConnectedEv, ConnectFailureEv, LoggedOutEv, PairStatusEv, TemporaryBanEv
    from neonize.utils.enum import ChatPresence, ChatPresenceMedia

    cliente = NewClient(sessao, uuid="cabine")
    cliente.event.qr(lambda _c, dados: eventos.put(("qr", dados.decode())))
    cliente.event(PairStatusEv)(lambda _c, ev: eventos.put(("conectado", ev.ID.User) if not ev.Error else ("erro", f"pareamento falhou: {ev.Error}")))
    cliente.event(ConnectedEv)(lambda c, _ev: eventos.put(("conectado", c.me.JID.User if c.me else "")))
    cliente.event(LoggedOutEv)(lambda _c, _ev: eventos.put(("deslogado", "O celular desconectou a cabine. Conecte de novo.")))
    cliente.event(TemporaryBanEv)(lambda _c, ev: eventos.put(("bloqueado", f"O WhatsApp bloqueou envios temporariamente (código {ev.Code}). Envios pausados.")))
    cliente.event(ConnectFailureEv)(lambda _c, ev: eventos.put(("erro", f"falha de conexão (motivo {ev.Reason})")))
    threading.Thread(target=cliente.connect, daemon=True).start()
    while True:
        comando, job, pedido = pedidos.get()
        if comando == "sair":
            try:
                cliente.logout()
            finally:
                eventos.put(("deslogado", None))
            continue
        imagem_enviada = False
        try:
            if not cliente.is_logged_in:
                raise RuntimeError("o celular da cabine não está conectado")
            resposta = cliente.is_on_whatsapp(f"+{pedido['numero']}")
            if not resposta or not resposta[0].IsIn:
                eventos.put(("resultado", job, "sem_whatsapp", None))
                continue
            jid, dados = resposta[0].JID, Path(pedido["caminho"]).read_bytes()
            cliente.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_COMPOSING, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
            time.sleep(random.uniform(1.5, 3.5))
            enviada = cliente.send_image(jid, dados, caption=pedido["legenda"])
            imagem_enviada = True
            if pedido["arquivo"]:
                time.sleep(random.uniform(1.0, 2.5))
                cliente.send_document(jid, dados, caption="Arquivo em qualidade máxima, sem a compressão do WhatsApp.", filename=pedido["nome"], mimetype="image/jpeg")
            eventos.put(("resultado", job, "ok", getattr(enviada, "ID", "")))
        except Exception as erro:
            eventos.put(("resultado", job, "parcial" if imagem_enviada else "falhou", str(erro)))


def iniciar():
    if _processo[0] and _processo[0].is_alive():
        if estado["status"] != "bloqueado":
            return
        _parar()
    _filas.update(pedidos=_contexto.Queue(), eventos=_contexto.Queue())
    _processo[0] = _contexto.Process(target=_filho, args=(SESSAO.as_posix(), _filas["pedidos"], _filas["eventos"]), daemon=True, name="whatsapp-celular")
    _processo[0].start()
    estado.update(status="conectando", qr=None, erro=None)
    _ultimo["visto"] = time.monotonic()
    if not any(t.name == "whatsapp-celular-leitor" for t in threading.enumerate()):
        threading.Thread(target=_ler, daemon=True, name="whatsapp-celular-leitor").start()


def _parar(**novo_estado):
    if _processo[0]:
        _processo[0].kill()
        _processo[0].join(5)
        _processo[0] = None
    estado.update(qr=None, **novo_estado)
    for evento, resultado in _pendentes.values():
        resultado.append(("falhou", "o WhatsApp parou"))
        evento.set()


def _ler():
    while True:
        try:
            tipo, *dados = _filas["eventos"].get(timeout=2)
        except (queue.Empty, OSError, ValueError, EOFError):
            tipo, dados = None, []
        if tipo == "qr":
            estado.update(status="aguardando_qr", qr=dados[0], erro=None)
            _ultimo["visto"] = time.monotonic()
        elif tipo == "conectado" and estado["status"] != "bloqueado":
            estado.update(status="conectado", qr=None, numero=dados[0] or estado["numero"], erro=None)
        elif tipo == "resultado" and dados[0] in _pendentes:
            _pendentes[dados[0]][1].append((dados[1], dados[2]))
            _pendentes[dados[0]][0].set()
        elif tipo == "deslogado":
            _parar(status="desligado", numero=None, erro=dados[0])
        elif tipo == "bloqueado":
            estado.update(status="bloqueado", erro=dados[0])
        elif tipo == "erro":
            estado["erro"] = dados[0]
        processo = _processo[0]
        if not processo:
            continue
        if estado["status"] in ("conectando", "aguardando_qr") and time.monotonic() - _ultimo["visto"] > QR_VALIDADE:
            _parar(status="desligado", erro="O QR Code expirou. Clique em “Conectar celular” para gerar outro.")
        elif not processo.is_alive():
            _parar(status="desligado", erro="O módulo do WhatsApp parou; reconectando…")
            if SESSAO.exists():
                time.sleep(5)
                iniciar()


def desconectar():
    if estado["status"] == "conectado" and _processo[0]:
        _filas["pedidos"].put(("sair", "", None))
        for _ in range(20):
            if estado["status"] != "conectado":
                break
            time.sleep(0.5)
    _parar(status="desligado", numero=None, erro=None)


def enviar(destino, caminho, nome_arquivo, evento="", arquivo=True):
    if estado["status"] != "conectado":
        raise ErroCelular(estado["erro"] or "o celular da cabine não está conectado", repetir=True)
    with _trava:
        espera = _ultimo["envio"] + random.uniform(*INTERVALO) - time.time()
        if espera > 0:
            time.sleep(espera)
        job, pronto = secrets.token_hex(4), threading.Event()
        _pendentes[job] = [pronto, []]
        legenda = random.choice(LEGENDAS).format(evento=evento or "SENAI")
        pedido = {"numero": destino, "caminho": str(caminho), "nome": nome_arquivo, "legenda": legenda, "arquivo": arquivo}
        _filas["pedidos"].put(("enviar", job, pedido))
        terminou = pronto.wait(120)
        resultado = _pendentes.pop(job)[1]
        _ultimo["envio"] = time.time()
    if not terminou or not resultado:
        raise ErroCelular("o WhatsApp não respondeu a tempo", repetir=True)
    situacao, detalhe = resultado[0]
    if situacao != "ok" and re.search(r"\b463\b", str(detalhe)):
        estado.update(status="bloqueado", erro=RESTRICAO)
    if situacao == "sem_whatsapp":
        raise ErroCelular("este número não tem WhatsApp", repetir=False)
    if situacao == "falhou":
        raise ErroCelular(f"falha ao enviar: {detalhe}", repetir=True)
    return detalhe or situacao
