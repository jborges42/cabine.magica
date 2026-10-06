# Cabine Mágica — SENAI Fraiburgo

Cabine de fotos: mostra a câmera ao vivo com a moldura do evento, tira a foto pelo teclado,
salva no computador e pede o WhatsApp para envio posterior.

## Rodar

Requer só Python 3.10+ (nenhuma dependência) e Google Chrome ou Edge.

```bash
python3 cabine.py        # abre http://127.0.0.1:8765
```

Na primeira vez, permita o acesso à câmera. Para o evento, abra em modo quiosque (tela cheia,
sem barra do navegador; feche com Alt+F4 / Cmd+Q):

```bash
# Windows
start chrome --kiosk http://127.0.0.1:8765
# macOS
open -a "Google Chrome" --args --kiosk http://127.0.0.1:8765
```

## Teclas

| Tela | Tecla | Ação |
|---|---|---|
| Câmera ao vivo | `Enter` / `Espaço` / passador de slides | Contagem 3‑2‑1 e foto |
| | `C` | Trocar de câmera (USB ↔ embutida) |
| | `F` | Tela cheia |
| Revisão | `0`–`9`, `⌫` | Digitar o WhatsApp |
| | `Enter` | Enviar (ou concluir sem número) |
| | `Esc` | Tirar outra foto |

O fluxo da pessoa usa só o teclado numérico. Sem interação, a revisão volta para a câmera em 60 s.

**Câmera fotográfica:** funciona se aparecer como webcam (placa de captura HDMI/USB ou o
utilitário de webcam do fabricante, como o EOS Webcam Utility). Escolha a câmera com `C`;
a escolha fica memorizada.

## Personalizar a moldura

Edite `web/config.json` e recarregue a página:

| Chave | Exemplo | O que faz |
|---|---|---|
| `titulo`, `subtitulo`, `hashtag` | `"MUNDO SENAI 2026"` | Textos da faixa (encolhem sozinhos se não couberem) |
| `cor_inicio`, `cor_fim` | `"#0A2A6B"` | Degradê da moldura (também colorem a interface) |
| `cor_destaque`, `cor_texto_destaque` | `"#FFC21A"` | Selo da hashtag e botões |
| `moldura_png` | `"moldura.png"` | Arte pronta (PNG transparente, mesma proporção da câmera, ex. 1920×1080) colocada em `web/`; substitui a moldura desenhada |
| `espelhar` | `true` | Prévia e foto espelhadas (efeito selfie) |
| `contagem` | `3` | Segundos da contagem regressiva |
| `resolucao` | `[1920, 1080]` | Resolução pedida à câmera |

## Fotos e integrações (WhatsApp, e-mail)

- Toda foto é salva na hora em `fotos/AAAAMMDD-HHMMSS-xxxxxx.jpg`, com a moldura.
- Quando a pessoa informa o número, a cabine cria `fila/<mesmo-id>.json`:

```json
{
  "foto": "20261006-183800-82267b.jpg",
  "canal": "whatsapp",
  "destino": "5549999991234",
  "status": "pendente",
  "criado_em": "2026-10-06T18:38:02"
}
```

A integração é um processo separado que lê `fila/*.json` com `status: "pendente"`, envia
`fotos/<foto>` para `destino` (por exemplo, pela WhatsApp Cloud API) e grava `status: "enviado"`
(ou `"erro"`). Assim a cabine nunca trava esperando a internet, e os envios que falharem podem
ser repetidos. Um canal de e-mail segue o mesmo formato com `"canal": "email"`.

> Os números de WhatsApp são dados pessoais (LGPD): use-os só para o envio e apague a `fila/`
> depois do evento.

## Teste

```bash
python3 test_cabine.py   # sobe o servidor e valida API, fila e validação do número
```
