# Cabine Mágica, SENAI Fraiburgo

Cabine de fotos para eventos. Ela mostra a câmera ao vivo com a moldura do evento e tira a foto pelo teclado, na resolução máxima da câmera. A foto recebe correções de luz e cor e fica salva no computador. O visitante recebe a foto pelo WhatsApp, no número que digita na tela, ou baixa pelo QR Code. Tudo é configurado num painel do operador.

## Instalar e rodar

Requer Python 3.10+ e Google Chrome ou Edge.

```bash
pip install -r requirements.txt     # OpenCV, QR Code e WhatsApp (neonize)
python cabine.py                    # no Windows: py cabine.py; abre http://127.0.0.1:8765
```

- macOS: `brew install libmagic cloudflared` (no Windows não precisa de libmagic).
- Windows: baixe `cloudflared-windows-amd64.exe` nas releases da Cloudflare no GitHub e deixe na pasta da cabine. É ele que gera o link público do QR de download.

Na primeira vez, permita o acesso à câmera. Os registros vão para `cabine.log`.

No evento, use o modo quiosque com um perfil próprio:

```bash
# Windows
py cabine.py --sem-navegador
start chrome --kiosk --user-data-dir=%LOCALAPPDATA%\cabine http://127.0.0.1:8765
# macOS
python3 cabine.py --sem-navegador
open -na "Google Chrome" --args --kiosk --user-data-dir=$HOME/.cabine-chrome http://127.0.0.1:8765
```

Deixe a energia em "nunca desligar a tela".

## Painel do operador

Abra http://127.0.0.1:8765/operador.html no mesmo computador. Ele tem duas abas.

### Cabine e evento

| Grupo | O que dá para mudar |
|---|---|
| Evento | Nome do evento, unidade, hashtag, cor principal e cor de destaque |
| Moldura e logo | Moldura SENAI desenhada com esses textos, ou uma arte própria em PNG transparente. Logo SENAI, logo próprio em PNG ou sem logo |
| Opções na cabine | Formatos habilitados (Story, Feed, Quadrado, Grande) e o inicial. Ajustes habilitados e o inicial. Liga e desliga: pedir o WhatsApp, QR Code para baixar, prévia espelhada, foto salva espelhada |
| Câmera e foto | Contagem regressiva, resolução, quadros por segundo e qualidade do arquivo final |

A prévia ao lado usa o mesmo desenho da cabine.

**Salvar e aplicar na cabine** grava `evento.json`. A cabine aplica a mudança em até 3 segundos, assim que estiver na tela ao vivo, sem interromper quem está na revisão. O servidor valida cada campo.

Com arte própria, a foto é recortada na proporção da arte e a escolha de formato some da cabine. As imagens enviadas ficam em `web/evento/`.

### WhatsApp

Conecta o emissor, define os limites de envio e mostra a fila. Também permite enviar um teste.

## Teclas

| Tela | Tecla | Ação |
|---|---|---|
| Câmera ao vivo | `1` a `4` | Formatos habilitados no painel, na ordem. A prévia já mostra o recorte |
| | `Enter`, `Espaço` ou passador de slides | Contagem regressiva e foto |
| | `C` | Trocar de câmera (a escolha fica memorizada) |
| | `F` | Tela cheia |
| Revisão | `0` a `9`, `⌫` | Digitar o WhatsApp (funciona com o NumLock desligado) |
| | `+` / `−` | Trocar o ajuste da foto |
| | `Enter` | Enviar, ou concluir sem número |
| | `Esc` | Tirar outra foto |

## Envio pelo WhatsApp (grátis, pelo celular da cabine)

1. No painel, abra a aba WhatsApp, escolha **Celular da cabine** e clique em **Conectar celular**.
2. No celular com o chip do evento, abra o WhatsApp e vá em Configurações > Aparelhos conectados > Conectar aparelho. Escaneie o QR do painel.
3. Cada número digitado na cabine recebe a foto como imagem e, se a opção estiver ligada, também como arquivo em qualidade total. A sessão fica salva em `whatsapp-celular.sqlite3` e a cabine reconecta sozinha.

O envio usa a biblioteca [neonize](https://github.com/krypton-byte/neonize), feita sobre a [whatsmeow](https://github.com/tulir/whatsmeow). Ela não é oficial: a cabine funciona como um "WhatsApp Web" automático. Os Termos de Uso do WhatsApp proíbem clientes não oficiais e envio automatizado. Por isso, o WhatsApp não publica nenhum limite que seja seguro.

Para reduzir o risco de perder o número:

- **Use um chip só para o evento.** Nunca use o número pessoal nem o oficial do SENAI.
- **Aqueça o chip por uns dias antes.** Coloque foto de perfil e o nome "SENAI Fraiburgo · Cabine Mágica", e converse à mão com a equipe. Vincule a cabine uma vez só e não refaça o vínculo durante o evento.
- **Ajuste os limites no painel.** O padrão é 15 envios por hora e 50 por dia. Relatos da comunidade mostram restrição a partir de 15 a 40 mensagens por dia para quem nunca falou com o número. O que passar do limite espera na fila.
- **Considere enviar só a imagem.** O arquivo em qualidade total dobra as mensagens por visitante. Sem ele, a alta qualidade continua disponível pelo QR de download.
- **Proteções automáticas da cabine:**
  - confere se o número tem WhatsApp antes de enviar;
  - espera de 8 a 20 segundos entre envios;
  - mostra "digitando…" e varia a legenda, que leva o nome do evento;
  - pede um 👍 de resposta.
- **Se o WhatsApp sinalizar bloqueio** (bloqueio temporário ou erro 463 de restrição), os envios param. Não escaneie o QR de novo. Espere a restrição acabar e clique em **Reconectar**.
- **Ao fim do evento:** clique em **Desconectar** no painel e apague `whatsapp-celular.sqlite3`.

O caminho de menor risco é inverter o fluxo: o visitante manda a primeira mensagem e a cabine responde. Esse fluxo ainda não foi implementado.

Os modos oficiais (360dialog e Cloud API da Meta) continuam no painel para quando houver orçamento. Eles custam cerca de R$ 0,035 por foto, com template aprovado.

## QR Code para baixar

Na revisão aparece um QR que abre, no celular do visitante, uma página com a foto em qualidade total e os botões Salvar e Compartilhar. Ele usa um túnel gratuito da Cloudflare, sem conta. O túnel expõe só as fotos, por links assinados. O resto da cabine continua acessível apenas no próprio PC.

Sem `cloudflared`, sem internet ou com a opção desligada no painel, o QR não aparece. Teste no Wi-Fi do evento, porque algumas redes bloqueiam `trycloudflare.com`.

## Qualidade da foto

- A resolução "Máxima da câmera" abre a câmera no maior modo nativo (4K numa webcam 4K). A prévia é desenhada no tamanho da tela, e a foto em resolução total.
- O original fica em `fotos/originais/`. O final, tratado e com moldura, fica em `fotos/` e é o que vai pelo WhatsApp.
- Uma câmera fotográfica funciona como webcam por meio de uma placa de captura HDMI (até 4K). Usar a resolução nativa do sensor exigiria integração com digiCamControl (Windows) ou gphoto2 (macOS), que ainda não foi feita.

## Ajustes da foto (presets)

São correções discretas, como as de um fotógrafo, feitas com OpenCV (`tratamento.py`). Cada uma leva menos de 0,6 s em 4K numa CPU comum. A moldura entra depois do ajuste, então as cores da marca nunca mudam.

| Preset | O que faz |
|---|---|
| Natural (padrão) | Ruído de cor, balanço de branco, exposição pela cena, pontos de preto e branco, sombras e realces, contraste local leve e nitidez |
| Luz de estúdio | Natural mais um "rebatedor" que ilumina os rostos (detectados com YuNet) |
| Pele suave | Natural mais uma suavização leve, só na pele dos rostos |
| Vívido | Natural mais vibração que poupa tons de pele |
| P&B clássico | Preto e branco com mistura de canais que favorece a pele |
| Original | Sem ajuste, só a moldura |

Para comparar os presets numa foto: `python tratamento.py foto.jpg`.

Não há preset de IA. Os modelos open source de realce de luz testados (SCI, Zero‑DCE++, IAT) pioraram fotos bem iluminadas. Os bons modelos de cor e de rosto (Deep WB, Exposure Correction, CodeFormer, MIRNet) têm licença não comercial.

O maior ganho de qualidade vem da luz, não do software: luz contínua de 5600 K na frente das pessoas e, se a webcam permitir, balanço de branco e exposição travados no programa dela.

## Identidade visual

Segue o modelo oficial SENAI 2026:

- azul `#164193` e laranja `#E84910`;
- fonte Century Gothic;
- assinatura branca sobre azul, com divisor;
- barra lateral com corte diagonal de cerca de 36°.

A Century Gothic é usada quando está instalada (vem com o Microsoft Office). Sem ela, entra a TeX Gyre Adventor, que é um clone livre (`web/fontes/`, licença GUST). A interface não depende de internet.

## LGPD

Fotos (rostos, muitas de menores) e números de WhatsApp são dados pessoais. A tela informa o uso ao pedir o número.

Depois dos envios, apague:

- `fotos/`
- `fila/`
- `molduras/`
- `segredo.key` (isso invalida os links de download)
- `whatsapp-celular.sqlite3`

Nenhum desses arquivos vai para o git.

## Testes

```bash
python test_cabine.py   # API, evento, tratamento, moldura, fila, limites e envio contra uma API falsa
python tratamento.py    # auto-teste dos presets
python whatsapp.py      # auto-teste da classificação de erros e do limite de 5 MB
```

## Desenvolvimento

O repositório segue o git flow:

- `main` guarda as versões publicadas, marcadas com tags.
- `develop` integra o trabalho.
- Cada mudança nasce num ramo `feature/`, `bugfix/` ou `hotfix/`.

O histórico de versões está no [CHANGELOG](CHANGELOG.md).
