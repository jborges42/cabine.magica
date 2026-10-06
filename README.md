# Cabine Mágica — SENAI Fraiburgo

Cabine de fotos: mostra a câmera ao vivo com a moldura do evento, tira a foto pelo teclado em
resolução máxima, aplica correções profissionais de luz e cor, salva no computador e envia a foto
pelo **WhatsApp oficial** para o número que a pessoa digita.

## Instalar e rodar

Requer Python 3.10+ e Google Chrome ou Edge.

```bash
pip install -r requirements.txt     # OpenCV, QR Code e WhatsApp (neonize)
python cabine.py                    # no Windows: py cabine.py — abre http://127.0.0.1:8765
```

- **macOS:** `brew install libmagic cloudflared` (no Windows não precisa de libmagic).
- **Windows:** baixe `cloudflared-windows-amd64.exe` das releases do GitHub da Cloudflare e
  deixe na pasta da cabine (é ele que gera o link público do QR de download).

Na primeira vez, permita o acesso à câmera. Registros vão para `cabine.log`.
Para o evento, use o modo quiosque, com perfil próprio:

```bash
# Windows
py cabine.py --sem-navegador
start chrome --kiosk --user-data-dir=%LOCALAPPDATA%\cabine http://127.0.0.1:8765
# macOS
python3 cabine.py --sem-navegador
open -na "Google Chrome" --args --kiosk --user-data-dir=$HOME/.cabine-chrome http://127.0.0.1:8765
```

Deixe a energia em "nunca desligar a tela".

## Teclas

| Tela | Tecla | Ação |
|---|---|---|
| Câmera ao vivo | `1` `2` `3` `4` | Formato: Story 9:16 · Feed 4:5 · Quadrado 1:1 · Grande (quadro inteiro). A prévia já mostra o recorte |
| | `Enter` / `Espaço` / passador de slides | Contagem 3‑2‑1 e foto |
| | `C` | Trocar de câmera (a escolha fica memorizada) |
| | `F` | Tela cheia |
| Revisão | `0`–`9`, `⌫` | Digitar o WhatsApp (funciona com o NumLock desligado) |
| | `+` / `−` | Trocar o ajuste da foto (Natural, Luz de estúdio…) |
| | `Enter` | Enviar (ou concluir sem número) |
| | `Esc` | Tirar outra foto |

## Envio pelo WhatsApp (grátis, pelo celular da cabine)

1. Abra **http://127.0.0.1:8765/operador.html** → **Celular da cabine** → **Conectar celular**.
2. No celular com o **chip do evento**: WhatsApp → Configurações → **Aparelhos conectados** →
   Conectar aparelho → escaneie o QR do painel.
3. Pronto: cada número digitado na cabine recebe a foto como **imagem** e como **arquivo em
   qualidade total**. A sessão fica salva (`whatsapp-celular.sqlite3`); a cabine reconecta sozinha.

**Isto não é a API oficial** (funciona como um "WhatsApp Web" automático). Para não perder o número:

- Use um **chip só para o evento**, nunca o número pessoal nem o oficial do SENAI.
- Ative o chip uns dias antes: foto de perfil, nome "SENAI Fraiburgo · Cabine Mágica", conversas normais.
- A cabine se protege: confere se o número tem WhatsApp, espera 8–20 s entre envios, mostra
  "digitando…", varia a legenda e pede um 👍 de resposta. Se o WhatsApp sinalizar bloqueio
  temporário, os envios param na hora e o painel avisa.
- ~200 envios/dia é um volume baixo para esse cuidado. Teste antes com o seu número ("Enviar um teste").
- Ao fim do evento: **Desconectar** no painel e apague `whatsapp-celular.sqlite3`.

A biblioteca roda num processo separado: se ela falhar, a cabine continua e reconecta sozinha.
Os modos oficiais (360dialog, Cloud API da Meta) continuam no painel, para quando houver orçamento
(cerca de R$ 0,035 por foto, com template aprovado).

## QR Code para baixar

Na revisão aparece um QR que abre, no celular do visitante, uma página com a foto em qualidade
total e os botões **Salvar** e **Compartilhar** (Story, WhatsApp…). Ele usa um túnel gratuito
da Cloudflare (sem conta), que expõe **só** as fotos por links assinados; o resto da cabine segue
acessível apenas no próprio PC. Sem `cloudflared` ou sem internet, o QR simplesmente não aparece.
Teste no Wi-Fi do evento: algumas redes bloqueiam `trycloudflare.com`.

## Qualidade da foto

- `resolucao: "max"` abre a câmera no maior modo nativo (4K numa webcam 4K). A prévia é desenhada
  no tamanho da tela; a foto, em resolução total (JPEG 95 % para o original).
- O original fica em `fotos/originais/`. O final, tratado e com moldura, fica em `fotos/` e é
  o que vai pelo WhatsApp.
- A prévia e a foto salva são espelhadas, como um espelho (`espelhar_foto` no config muda isso).
- **Câmera fotográfica:** funciona como webcam por placa de captura HDMI (até 4K). A resolução
  nativa do sensor exige integração com digiCamControl (Windows) ou gphoto2 (macOS), que ainda
  não foi implementada.

## Ajustes da foto (presets)

Correções discretas, como as de um fotógrafo, feitas com OpenCV (`tratamento.py`). Cada uma leva
menos de 0,6 s em 4K numa CPU comum. A moldura entra depois do ajuste, então as cores da marca
nunca mudam.

| Preset | O que faz |
|---|---|
| Natural (padrão) | Ruído de cor, balanço de branco, exposição pela cena, pontos de preto e branco, sombras e realces, contraste local leve e nitidez |
| Luz de estúdio | Natural + um "rebatedor" que ilumina os rostos (detectados com YuNet) |
| Pele suave | Natural + suavização bem leve, só na pele dos rostos |
| Vívido | Natural + vibração que poupa tons de pele |
| P&B clássico | Preto e branco com mistura de canais que favorece a pele |
| Original | Sem ajuste, só a moldura |

A exposição é calculada pela cena, não pelo rosto, para não "clarear" tons de pele.
Para comparar os presets numa foto: `python tratamento.py foto.jpg`.

**Por que não há preset de IA.** Testamos modelos open source de realce de luz (SCI,
Zero‑DCE++, IAT): todos pioraram fotos bem iluminadas (estouraram, lavaram ou escureceram).
Os modelos bons de cor e de rosto (Deep WB, Exposure Correction, CodeFormer, MIRNet) têm
licença **não comercial**, inadequada para uso institucional. O caminho de IA que vale para o
futuro é o *Image‑Adaptive 3D LUT* (Apache‑2.0), treinado com fotos da cabine editadas por um
fotógrafo do SENAI.

**O maior ganho de qualidade não é software:** luz contínua de 5600 K na frente das pessoas e,
se a webcam permitir, balanço de branco e exposição travados no software dela (Logi Tune etc.).

## Personalizar (`web/config.json`)

| Chave | Exemplo | O que faz |
|---|---|---|
| `titulo`, `unidade`, `hashtag` | `"MUNDO SENAI 2026"` | Textos da moldura (encolhem sozinhos se não couberem) |
| `cor_primaria`, `cor_destaque` | `"#164193"`, `"#E84910"` | Azul e laranja SENAI (moldura e interface) |
| `logo` | `"logo-senai-branco.png"` | Assinatura na faixa (versão branca, sem margem) |
| `moldura_png` | `"moldura.png"` | Arte pronta (PNG transparente em `web/`). A foto é recortada no centro para a proporção da arte |
| `preset` | `"natural"` | Ajuste aplicado de início |
| `resolucao` | `"max"` ou `[1920, 1080]` | Resolução pedida à câmera |
| `fps` | `30` | Baixe para 15 se a prévia em 4K engasgar num PC fraco |
| `espelhar_previa`, `espelhar_foto` | `true`, `true` | Espelhamento da prévia e da foto salva |
| `formato` | `"feed"` | Formato inicial: `story`, `feed`, `quadrado` ou `grande` |
| `contagem` | `3` | Segundos da contagem regressiva |
| `qualidade_jpeg` | `0.92` | Qualidade do arquivo final |

### Identidade visual

Segue o modelo oficial SENAI 2026 (`ref/`): azul `#164193`, laranja `#E84910`, Century Gothic,
assinatura branca sobre azul com divisor, e a barra lateral com corte diagonal de cerca de 36°,
cujas proporções são reproduzidas na moldura e na borda da tela. A Century Gothic é usada quando
está instalada (vem com o Microsoft Office). Sem ela entra a TeX Gyre Adventor (`web/fontes/`,
licença GUST, clone livre). A cabine não depende de internet para a interface.

## LGPD

Fotos (rostos, muitas de menores) e números de WhatsApp são dados pessoais. A tela informa o
uso ao pedir o número. Depois dos envios, apague `fotos/`, `fila/`, `molduras/`, `segredo.key`
(invalida os links de download) e `whatsapp-celular.sqlite3`.

## Testes

```bash
python test_cabine.py   # API, tratamento, moldura, fila e envio do WhatsApp contra uma API falsa
python tratamento.py    # auto-teste dos presets
python whatsapp.py      # auto-teste da classificação de erros e do limite de 5 MB
```
