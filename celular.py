"""WhatsApp pelo celular da cabine, de graça: o celular lê um QR Code e vira o emissor, e a
cabine envia a foto para o número que o visitante digitou (imagem + arquivo em qualidade total).

Usa a biblioteca neonize (whatsmeow), que NÃO é oficial. Para reduzir o risco de bloqueio:
chip dedicado ao evento, confirmação de que o número tem WhatsApp antes de enviar, ritmo humano
entre envios, "digitando…" antes de mandar e legendas variadas (texto idêntico para centenas de
desconhecidos é a marca de disparo em massa).
"""
import random
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SESSAO = RAIZ / "whatsapp-celular.sqlite3"  # credenciais do aparelho vinculado: não compartilhe
INTERVALO = (8.0, 20.0)  # segundos entre envios: ~200/dia cabem folgados
LEGENDAS = (
    "Olá! Aqui está a sua foto da Cabine Mágica do SENAI Fraiburgo 📸 Obrigado pela visita! Responda com um 👍 se recebeu.",
    "Oi! Sua foto do Mundo SENAI 2026 chegou 😄 Que bom que você passou na Cabine Mágica! Manda um 👍 pra gente saber que deu certo.",
    "Prontinho! Essa é a sua foto da Cabine Mágica do SENAI Fraiburgo ✨ Se puder, responda com um 👍 confirmando o recebimento.",
)
estado = {"status": "desligado", "qr": None, "numero": None, "erro": None}
_cliente = []
_trava = threading.Lock()  # um envio por vez
_ultimo_envio = [0.0]


class ErroCelular(Exception):
    def __init__(self, mensagem, repetir):
        super().__init__(mensagem)
        self.repetir = repetir


def iniciar():
    """Conecta usando a sessão salva; sem sessão, gera o QR para o operador escanear."""
    if _cliente:
        return
    try:
        from neonize.client import NewClient
        from neonize.events import ConnectedEv, LoggedOutEv
    except Exception as erro:  # sem neonize ou sem libmagic (no Mac: brew install libmagic)
        estado.update(status="erro", erro=f"biblioteca do WhatsApp indisponível: {erro}")
        return
    cliente = NewClient(str(SESSAO), uuid="cabine")

    def qr(_c, dados):
        estado.update(status="aguardando_qr", qr=dados.decode(), erro=None)

    def conectado(c, _evento):
        estado.update(status="conectado", qr=None, numero=c.get_me().JID.User, erro=None)

    def saiu(_c, _evento):  # desconectado pelo celular (Aparelhos conectados)
        _cliente.clear()
        estado.update(status="desligado", qr=None, numero=None, erro="O celular desconectou a cabine. Conecte de novo.")

    cliente.event.qr(qr)
    cliente.event(ConnectedEv)(conectado)
    cliente.event(LoggedOutEv)(saiu)
    _cliente.append(cliente)
    estado.update(status="conectando", erro=None)
    threading.Thread(target=cliente.connect, daemon=True, name="whatsapp-celular").start()


def desconectar():
    """Tira a cabine dos aparelhos conectados do celular."""
    if _cliente:
        try:
            _cliente[0].logout()
        except Exception:
            pass
        _cliente.clear()
    estado.update(status="desligado", qr=None, numero=None, erro=None)


def enviar(destino, jpeg, nome_arquivo):
    """Envia para o número digitado ('55DD9XXXXXXXX'): a foto como imagem (aparece no chat) e
    como documento (arquivo sem a compressão do WhatsApp). Devolve o id da mensagem."""
    from neonize.utils.enum import ChatPresence, ChatPresenceMedia

    if estado["status"] != "conectado" or not _cliente:
        raise ErroCelular("o celular da cabine não está conectado", repetir=True)
    cliente = _cliente[0]
    with _trava:
        espera = _ultimo_envio[0] + random.uniform(*INTERVALO) - time.time()
        if espera > 0:
            time.sleep(espera)
        try:
            # Confirma que o número tem WhatsApp e pega o identificador certo (resolve o 9º dígito).
            resposta = cliente.is_on_whatsapp(f"+{destino}")
            if not resposta or not resposta[0].IsIn:
                raise ErroCelular("este número não tem WhatsApp", repetir=False)
            jid = resposta[0].JID
            cliente.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_COMPOSING, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
            time.sleep(random.uniform(1.5, 3.5))  # "digitando…", como uma pessoa
            enviada = cliente.send_image(jid, jpeg, caption=random.choice(LEGENDAS))
            time.sleep(random.uniform(1.0, 2.5))
            cliente.send_document(jid, jpeg, caption="Arquivo em qualidade máxima, sem a compressão do WhatsApp.", filename=nome_arquivo, mimetype="image/jpeg")
        except ErroCelular:
            raise
        except Exception as erro:  # rede ou sessão: tenta de novo depois
            raise ErroCelular(f"falha ao enviar: {erro}", repetir=True) from None
        finally:
            _ultimo_envio[0] = time.time()
    return getattr(enviada, "ID", "")
