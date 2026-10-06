# Changelog

## 1.0.0 (06/10/2026)

- Painel do operador com a aba Cabine e evento: nome do evento, unidade, hashtag, cores, arte própria da moldura, logo, formatos e ajustes habilitados, WhatsApp e QR de download liga/desliga, espelhamento, contagem, resolução, fps e qualidade, com prévia ao vivo da moldura.
- A cabine aplica a configuração sozinha, sem interromper a revisão; `web/config.json` deu lugar a `evento.json`, validado no servidor.
- Limites de envio por hora e por dia no modo celular, arquivo em qualidade total opcional e pausa automática na restrição 463.
- Legenda do WhatsApp com o nome do evento configurado.
- Código sem comentários, sem duplicações e sem parâmetros sem uso.

## 0.3.2 (06/10/2026)

- O processo do WhatsApp encerra junto com a cabine e não fica órfão.

## 0.3.1 (06/10/2026)

- QR de pareamento do WhatsApp legível (SVG escalável, margem e preto no branco).
- QR de download maior na revisão.

## 0.3.0 (06/10/2026)

- Formatos Story, Feed, Quadrado e Grande, escolhidos antes da foto com prévia do recorte.
- Foto espelhada como a prévia.
- QR Code para o visitante baixar a foto em qualidade total (túnel Cloudflare, links assinados).
- Modo celular gratuito: o WhatsApp da cabine é vinculado por QR e envia imagem e arquivo.
- Balanço de branco que não azula silhuetas em fundos coloridos.

## 0.2.0 (06/10/2026)

- Presets de tratamento (Natural, Luz de estúdio, Pele suave, Vívido, P&B, Original) com OpenCV e YuNet.
- Troca do ajuste na revisão; original guardado em resolução total.
- Câmera no maior modo nativo, com fps configurável.
- Envio pelo WhatsApp oficial (Cloud API e 360dialog) a partir da fila.
- Painel do operador para configurar, testar e acompanhar os envios.

## 0.1.0 (06/10/2026)

- Prévia ao vivo da webcam com a moldura do evento e foto pelo teclado.
- Servidor local que salva as fotos e registra os pedidos de envio em `fila/`.
- Campo de WhatsApp com teclado numérico na revisão.
- Identidade visual SENAI 2026: azul e laranja oficiais, Century Gothic, assinatura e barra lateral.
