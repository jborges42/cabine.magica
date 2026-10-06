"""WhatsApp pelo celular da cabine, de graça: o celular lê um QR Code e vira o emissor, e a
cabine envia a foto para o número que o visitante digitou (imagem + arquivo em qualidade total).

Usa a biblioteca neonize (whatsmeow), que NÃO é oficial. Para reduzir o risco de bloqueio:
chip dedicado ao evento, confirmação de que o número tem WhatsApp antes de enviar, ritmo humano
entre envios, "digitando…" antes de mandar e legendas variadas. Se o WhatsApp sinalizar
bloqueio temporário, os envios param na hora.

A biblioteca roda num PROCESSO SEPARADO: a parte em Go pode dar "panic" ou travar (verificado:
chamadas antes do pareamento derrubam o processo inteiro), e isso não pode levar a cabine junto.
"""
import multiprocessing
import queue
import random
import secrets
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SESSAO = RAIZ / "whatsapp-celular.sqlite3"  # credenciais do aparelho vinculado: não compartilhe
INTERVALO = (8.0, 20.0)  # segundos entre envios: ~200/dia cabem folgados
QR_VALIDADE = 75  # s sem QR novo nem conexão: o whatsmeow desiste e o processo é encerrado
LEGENDAS = (
    "Olá! Aqui está a sua foto da Cabine Mágica do SENAI Fraiburgo 📸 Obrigado pela visita! Responda com um 👍 se recebeu.",
    "Oi! Sua foto do Mundo SENAI 2026 chegou 😄 Que bom que você passou na Cabine Mágica! Manda um 👍 pra gente saber que deu certo.",
    "Prontinho! Essa é a sua foto da Cabine Mágica do SENAI Fraiburgo ✨ Se puder, responda com um 👍 confirmando o recebimento.",
)
estado = {"status": "desligado", "qr": None, "numero": None, "erro": None}
_contexto = multiprocessing.get_context("spawn")
_processo = [None]
_filas = {}
_pendentes = {}  # job → [evento, resultado]
_trava = threading.Lock()  # um envio por vez
_ultimo = {"envio": 0.0, "visto": 0.0}


class ErroCelular(Exception):
    def __init__(self, mensagem, repetir):
        super().__init__(mensagem)
        self.repetir = repetir


def _filho(sessao, pedidos, eventos):
    """Processo separado com o cliente do WhatsApp."""
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
    threading.Thread(target=cliente.connect, daemon=True).start()  # connect() bloqueia
    while True:
        comando, job, numero, caminho, nome = pedidos.get()
        if comando == "sair":
            try:
                cliente.logout()  # tira dos aparelhos conectados e apaga a sessão
            finally:
                eventos.put(("deslogado", None))
            continue
        imagem_enviada = False
        try:
            if not cliente.is_logged_in:
                raise RuntimeError("o celular da cabine não está conectado")
            # Confirma que o número tem WhatsApp e pega o identificador certo (resolve o 9º dígito).
            resposta = cliente.is_on_whatsapp(f"+{numero}")
            if not resposta or not resposta[0].IsIn:
                eventos.put(("resultado", job, "sem_whatsapp", None))
                continue
            jid, dados = resposta[0].JID, Path(caminho).read_bytes()
            cliente.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_COMPOSING, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
            time.sleep(random.uniform(1.5, 3.5))  # "digitando…", como uma pessoa
            enviada = cliente.send_image(jid, dados, caption=random.choice(LEGENDAS))
            imagem_enviada = True
            time.sleep(random.uniform(1.0, 2.5))
            cliente.send_document(jid, dados, caption="Arquivo em qualidade máxima, sem a compressão do WhatsApp.", filename=nome, mimetype="image/jpeg")
            eventos.put(("resultado", job, "ok", getattr(enviada, "ID", "")))
        except Exception as erro:
            # Se a imagem já foi, não repete o par (a pessoa receberia a foto em dobro).
            eventos.put(("resultado", job, "parcial" if imagem_enviada else "falhou", str(erro)))


def iniciar():
    """Sobe o processo do WhatsApp: com sessão salva, reconecta; sem ela, gera o QR."""
    if _processo[0] and _processo[0].is_alive():
        return
    _filas.update(pedidos=_contexto.Queue(), eventos=_contexto.Queue())  # filas novas: um kill pode corromper as antigas
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
    """Lê os eventos do processo do WhatsApp e cuida dele (QR vencido, queda, bloqueio)."""
    while True:
        try:
            tipo, *dados = _filas["eventos"].get(timeout=2)
        except (queue.Empty, OSError, ValueError, EOFError):
            tipo, dados = None, []
        if tipo == "qr":
            estado.update(status="aguardando_qr", qr=dados[0], erro=None)
            _ultimo["visto"] = time.monotonic()
        elif tipo == "conectado":
            estado.update(status="conectado", qr=None, numero=dados[0] or estado["numero"], erro=None)
        elif tipo == "resultado" and dados[0] in _pendentes:
            _pendentes[dados[0]][1].append((dados[1], dados[2]))
            _pendentes[dados[0]][0].set()
        elif tipo == "deslogado":
            _parar(status="desligado", numero=None, erro=dados[0])
        elif tipo == "bloqueado":
            estado.update(status="bloqueado", erro=dados[0])  # para de enviar; o operador decide
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
                iniciar()  # tinha sessão: volta sozinho, sem novo QR


def desconectar():
    """Tira a cabine dos aparelhos conectados do celular (fim do evento)."""
    if estado["status"] == "conectado" and _processo[0]:
        _filas["pedidos"].put(("sair", "", "", "", ""))
        for _ in range(20):  # até 10 s para o logout
            if estado["status"] != "conectado":
                break
            time.sleep(0.5)
    _parar(status="desligado", numero=None, erro=None)  # antes do pareamento, o logout trava: só encerra


def enviar(destino, caminho, nome_arquivo):
    """Envia para o número digitado ('55DD9XXXXXXXX') a foto como imagem (aparece no chat) e
    como documento (arquivo sem a compressão do WhatsApp). Devolve o id da mensagem."""
    if estado["status"] != "conectado":
        raise ErroCelular(estado["erro"] or "o celular da cabine não está conectado", repetir=True)
    with _trava:
        espera = _ultimo["envio"] + random.uniform(*INTERVALO) - time.time()
        if espera > 0:
            time.sleep(espera)
        job, pronto = secrets.token_hex(4), threading.Event()
        _pendentes[job] = [pronto, []]
        _filas["pedidos"].put(("enviar", job, destino, str(caminho), nome_arquivo))
        terminou = pronto.wait(120)
        resultado = _pendentes.pop(job)[1]
        _ultimo["envio"] = time.time()
    if not terminou or not resultado:
        raise ErroCelular("o WhatsApp não respondeu a tempo", repetir=True)
    situacao, detalhe = resultado[0]
    if situacao == "sem_whatsapp":
        raise ErroCelular("este número não tem WhatsApp", repetir=False)
    if situacao == "falhou":
        raise ErroCelular(f"falha ao enviar: {detalhe}", repetir=True)
    return detalhe or situacao  # "parcial": a imagem chegou, o arquivo não (não repetir)
