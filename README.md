# Cabine Mágica — SENAI Fraiburgo

Cabine de fotos: mostra a câmera ao vivo com a moldura do evento, tira a foto pelo teclado em
resolução máxima, aplica correções profissionais de luz e cor, salva no computador e envia a foto
pelo **WhatsApp oficial** para o número que a pessoa digita.

## Instalar e rodar

Requer Python 3.10+ e Google Chrome ou Edge.

```bash
pip install -r requirements.txt     # numpy + OpenCV (tratamento das fotos)
python cabine.py                    # no Windows: py cabine.py — abre http://127.0.0.1:8765
```

Na primeira vez, permita o acesso à câmera. Registros vão para `cabine.log`.
Para o evento, use o modo quiosque, com perfil próprio, que funciona mesmo com o Chrome já aberto:

```bash
# Windows
py cabine.py --sem-navegador
start chrome --kiosk --user-data-dir=%LOCALAPPDATA%\cabine http://127.0.0.1:8765
# macOS
python3 cabine.py --sem-navegador
open -na "Google Chrome" --args --kiosk --user-data-dir=$HOME/.cabine-chrome http://127.0.0.1:8765
```

Deixe a energia em "nunca desligar a tela". A cabine também pede para a tela ficar acesa.

## Teclas

| Tela | Tecla | Ação |
|---|---|---|
| Câmera ao vivo | `Enter` / `Espaço` / passador de slides | Contagem 3‑2‑1 e foto |
| | `C` | Trocar de câmera (a escolha fica memorizada) |
| | `F` | Tela cheia |
| Revisão | `0`–`9`, `⌫` | Digitar o WhatsApp (funciona com o NumLock desligado) |
| | `+` / `−` | Trocar o ajuste da foto (Natural, Luz de estúdio…) |
| | `Enter` | Enviar (ou concluir sem número) |
| | `Esc` | Tirar outra foto |

A pessoa usa só o teclado numérico. Sem interação, a revisão volta para a câmera em 60 s.

## WhatsApp oficial (número emissor)

Abra **http://127.0.0.1:8765/operador.html**. Nele você conecta o número, testa o envio e
acompanha a fila (enviadas, pendentes, com erro, botão de reenviar). Há dois caminhos oficiais,
e a cabine funciona igual nos dois:

1. **Meu celular, lendo um QR Code (coexistência).** O número precisa estar no app
   **WhatsApp Business**, versão 2.24.17 ou superior, em uso há pelo menos 7 dias. O WhatsApp
   comum não serve, mas dá para migrar o número no próprio celular.
   - A Meta só libera esse QR Code por meio de um parceiro oficial (BSP), porque o fluxo exige
     ser Tech Provider e uma página HTTPS. Uma página local não consegue exibi-lo.
   - Recomendação: **360dialog**. No painel deles (Add channel), você lê o QR com o app
     Business e gera uma API key, que é colada no painel do operador.
   - O número continua no seu celular, e você vê lá cada foto enviada.
   - Abra o app pelo menos a cada 13 dias, senão a conexão cai.
2. **Número dedicado na Cloud API da Meta**, sem QR e sem intermediário.
   - Use um chip que não esteja no WhatsApp.
   - Gere um token permanente de System User e copie o Phone Number ID.
   - O passo a passo está no painel do operador.

**Antes do evento:**
- **Template:** crie e aprove (até 24 h) o template `foto_cabine_magica` com cabeçalho de
  imagem, conforme o texto no painel do operador. Quem nunca falou com o SENAI só pode receber
  template. Mantenha o texto neutro: se ficar promocional, a Meta muda a categoria para
  Marketing, que custa cerca de 9 vezes mais.
- **Verificação do CNPJ:** sem ela, o limite é de 250 pessoas por dia. A análise pode levar dias.
- **Teste com números reais do DDD 49:** há relatos de falha ligada ao 9º dígito fora de SP/RJ.
- **Custo:** utility no Brasil é US$ 0,0068 por mensagem, cerca de US$ 3,40 para 500 fotos.

**Como o envio funciona:**
- A cabine nunca espera a internet. O pedido vai para `fila/<id>.json`, e uma thread envia:
  sobe a foto, que é reduzida só se passar de 5 MB, e manda o template.
- Instabilidade é repetida com espera de 4, 16, 64 s… até 15 min.
- Token, pagamento ou template com problema **pausam** a fila e aparecem no painel.
- Número sem WhatsApp vira `erro`, e você reenvia pelo painel.
- As credenciais ficam em `whatsapp.json`, fora de `web/`, e nunca vão para o navegador.
  Não compartilhe esse arquivo.

Teste rápido pela linha de comando: `python whatsapp.py 49999991234` (manda a foto mais recente).

## Qualidade da foto

- `resolucao: "max"` abre a câmera no maior modo nativo (4K numa webcam 4K). A prévia é desenhada
  no tamanho da tela; a foto, em resolução total (JPEG 95 % para o original).
- O original fica em `fotos/originais/`. O final, tratado e com moldura, fica em `fotos/` e é
  o que vai pelo WhatsApp.
- A prévia é espelhada, como um espelho. A foto salva não é, então banners e camisetas saem
  legíveis.
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
| `espelhar_previa`, `espelhar_foto` | `true`, `false` | Espelhamento da prévia e da foto salva |
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
uso ao pedir o número. Depois dos envios, apague `fotos/`, `fila/` e `molduras/` ao fim do evento.

## Testes

```bash
python test_cabine.py   # API, tratamento, moldura, fila e envio do WhatsApp contra uma API falsa
python tratamento.py    # auto-teste dos presets
python whatsapp.py      # auto-teste da classificação de erros e do limite de 5 MB
```
