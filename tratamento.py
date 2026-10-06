"""Tratamento das fotos da cabine: correções discretas de fotógrafo (OpenCV).

Os presets trabalham no ORIGINAL, sem moldura; a moldura entra por último, então as
cores da marca nunca são alteradas. Cada preset recebe (imagem BGR uint8, rostos) e
devolve a imagem tratada. Comparar presets numa foto:  python tratamento.py foto.jpg
"""
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

YUNET = str(Path(__file__).with_name("modelos") / "face_detection_yunet_2026may.onnx")  # OpenCV Zoo, MIT
X = np.arange(256, dtype=np.float32) / 255
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)


def rostos(img):
    """Caixas (x, y, l, a) dos rostos (YuNet), procuradas numa cópia de 640 px: rápido até em 4K."""
    escala = min(1.0, 640 / max(img.shape[:2]))
    pequena = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    detector = cv2.FaceDetectorYN.create(YUNET, "", pequena.shape[1::-1], score_threshold=0.7)  # 1 por chamada: thread-safe
    _, caixas = detector.detect(pequena)
    return [tuple(int(v / escala) for v in caixa[:4]) for caixa in (caixas if caixas is not None else [])]


def balanco_branco(img, forca=0.5, limite=14):
    """Mundo cinza em LAB, parcial e limitado. Só votam pixels quase neutros (paredes, roupas
    claras): um fundo laranja ou um banner azul não "puxam" a correção."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    amostra = lab[::4, ::4]
    croma = np.hypot(amostra[..., 1] - 128, amostra[..., 2] - 128)
    votam = (amostra[..., 0] > 30) & (amostra[..., 0] < 230) & (croma < 30)
    if votam.mean() > 0.02:  # pouca coisa neutra na cena: melhor não mexer
        peso = lab[..., 0] / 255  # proporcional à luz: tons escuros (roupas) quase não mudam de cor
        for canal in (1, 2):
            desvio = np.clip(amostra[..., canal][votam].mean() - 128, -limite, limite)
            lab[..., canal] -= desvio * forca * peso
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def curva_luz(img, curva):
    """Aplica a curva só na luminosidade (L do LAB): a cor (matiz e saturação) não muda."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.LUT(lab[..., 0], np.clip(curva * 255, 0, 255).astype(np.uint8))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def exposicao(img, alvo=0.42, limites=(0.8, 1.3)):
    """Gama pela luminância média-logarítmica da CENA (não do rosto: não "clareia" tons de pele)."""
    luz = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[::4, ::4, 0].astype(np.float32) / 255
    chave = float(np.exp(np.log(luz + 0.01).mean()))
    gama = float(np.clip(np.log(alvo) / np.log(max(chave, 0.02)), *limites))
    return curva_luz(img, X**gama)


def niveis(img, corte=(0.4, 99.8), limites=(28, 215)):
    """Ponto de preto e de branco automáticos (o "Auto" dos Níveis), sem esticar demais."""
    preto, branco = np.percentile(cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[::4, ::4, 0], corte)
    preto, branco = min(preto, limites[0]), max(branco, limites[1])
    return curva_luz(img, np.clip((X * 255 - preto) / (branco - preto), 0, 1))


def tons(img, sombras=0.0, realces=0.0, contraste=0.0, local=0.0):
    """Curva só na luminosidade (LAB): abre sombras, segura realces, contraste em S e CLAHE suave."""
    curva = X + sombras * 6.75 * X * (1 - X) ** 2 - realces * 6.75 * X**2 * (1 - X)
    curva += contraste * (X * X * (3 - 2 * X) - X)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    luz = cv2.LUT(lab[..., 0], np.clip(curva * 255, 0, 255).astype(np.uint8))
    if local:
        clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(luz)
        luz = cv2.addWeighted(luz, 1 - local, clahe, local, 0)
    lab[..., 0] = luz
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def ruido(img):
    """Ruído de cor (o "granulado colorido" de webcam) some; o de luminância só é aparado."""
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    altura, largura = img.shape[:2]
    for canal in (1, 2):
        pequeno = cv2.resize(ycc[..., canal], (largura // 4, altura // 4), interpolation=cv2.INTER_AREA)
        ycc[..., canal] = cv2.resize(cv2.GaussianBlur(pequeno, (0, 0), 1.2), (largura, altura), interpolation=cv2.INTER_LINEAR)
    ycc[..., 0] = cv2.bilateralFilter(ycc[..., 0], 5, 18, 3)
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)


def nitidez(img, quantidade=0.35, limiar=3):
    """Máscara de nitidez na luminância, com limiar: realça bordas, não o granulado."""
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    luz = ycc[..., 0]
    detalhe = (luz.astype(np.int16) - cv2.GaussianBlur(luz, (0, 0), max(0.8, img.shape[1] / 1920))).astype(np.float32)
    detalhe[np.abs(detalhe) < limiar] = 0
    ycc[..., 0] = np.clip(luz + quantidade * detalhe, 0, 255).astype(np.uint8)
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)


def vibracao(img, quantidade=0.2):
    """Saturação que puxa mais as cores apagadas e poupa tons de pele."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    curva = lambda q: np.clip((X + q * X * (1 - X)) * 255, 0, 255).astype(np.uint8)
    pele = (hsv[..., 0] < 25) | (hsv[..., 0] > 165)
    hsv[..., 1] = np.where(pele, cv2.LUT(hsv[..., 1], curva(quantidade * 0.4)), cv2.LUT(hsv[..., 1], curva(quantidade)))
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def mascara_rostos(img, caixas, escala_elipse=1.0):
    """Máscara suave (0–1) em volta dos rostos, calculada em baixa resolução."""
    altura, largura = img.shape[:2]
    fator = min(1.0, 480 / max(altura, largura))
    mascara = np.zeros((int(altura * fator), int(largura * fator)), np.float32)
    for x, y, l, a in caixas:
        centro = (int((x + l / 2) * fator), int((y + a * 0.6) * fator))
        eixos = (int(l * 0.75 * escala_elipse * fator), int(a * 1.1 * escala_elipse * fator))
        cv2.ellipse(mascara, centro, eixos, 0, 0, 360, 1, -1)
    if caixas:
        mascara = cv2.GaussianBlur(mascara, (0, 0), max(l for _, _, l, _ in caixas) * fator * 0.35)
    return cv2.resize(mascara, (largura, altura), interpolation=cv2.INTER_LINEAR)[..., None]


def luz_nos_rostos(img, caixas, forca=0.14):
    """"Rebatedor" digital: ilumina os meios-tons em volta dos rostos, sem estourar realces."""
    if not caixas:
        return img
    f = img.astype(np.float32) / 255
    f += forca * mascara_rostos(img, caixas, 1.4) * 4 * f * (1 - f)
    return np.clip(f * 255, 0, 255).astype(np.uint8)


def pele_suave(img, caixas, forca=0.4):
    """Suavização bem leve, só na pele dentro da região dos rostos; a textura continua visível."""
    saida = img.copy()
    for x, y, l, a in caixas:
        x0, y0 = max(0, x - l // 4), max(0, y - a // 4)
        x1, y1 = min(img.shape[1], x + l + l // 4), min(img.shape[0], y + a + a // 2)
        recorte = img[y0:y1, x0:x1]
        fator = min(1.0, 320 / max(recorte.shape[:2]))
        pequeno = cv2.resize(recorte, None, fx=fator, fy=fator, interpolation=cv2.INTER_AREA)
        suave = cv2.resize(cv2.bilateralFilter(pequeno, 9, 28, 7), recorte.shape[1::-1], interpolation=cv2.INTER_LINEAR)
        ycc = cv2.cvtColor(recorte, cv2.COLOR_BGR2YCrCb)
        pele = cv2.inRange(ycc, (0, 133, 77), (255, 173, 127)).astype(np.float32) / 255
        pele = cv2.GaussianBlur(pele, (0, 0), max(2, l / 60))[..., None] * forca
        saida[y0:y1, x0:x1] = (recorte * (1 - pele) + suave * pele).astype(np.uint8)
    return saida


def preto_e_branco(img):
    """P&B com mistura de canais que favorece a pele, e curva em S clássica."""
    b, g, r = cv2.split(img.astype(np.float32))
    cinza = np.clip(0.38 * r + 0.50 * g + 0.12 * b, 0, 255).astype(np.uint8)
    return tons(cv2.cvtColor(cinza, cv2.COLOR_GRAY2BGR), contraste=0.25, local=0.3)


def natural(img, caixas):
    # Ordem de fotógrafo: ruído antes de clarear (senão o granulado sobe junto), nitidez por último.
    img = balanco_branco(ruido(img))
    img = niveis(exposicao(img))
    img = vibracao(tons(img, sombras=0.12, realces=0.10, local=0.35), 0.12)
    return nitidez(img)


PRESETS = {
    "natural": ("Natural", natural),
    "estudio": ("Luz de estúdio", lambda img, caixas: luz_nos_rostos(tons(natural(img, caixas), contraste=0.08), caixas, 0.12)),
    "pele": ("Pele suave", lambda img, caixas: pele_suave(natural(img, caixas), caixas)),
    "vivido": ("Vívido", lambda img, caixas: vibracao(tons(natural(img, caixas), contraste=0.12), 0.22)),
    "pb": ("P&B clássico", lambda img, caixas: preto_e_branco(natural(img, caixas))),
    "original": ("Original", lambda img, caixas: img),
}


@lru_cache(maxsize=4)
def _moldura(caminho, _mtime):
    return cv2.imread(caminho, cv2.IMREAD_UNCHANGED)


def aplicar_moldura(img, caminho):
    """Cola a moldura (PNG BGRA gerado pela interface) por cima da foto tratada."""
    caminho = Path(caminho)
    if not caminho.exists():
        return img
    moldura = _moldura(str(caminho), caminho.stat().st_mtime)
    if moldura.shape[:2] != img.shape[:2]:
        moldura = cv2.resize(moldura, img.shape[1::-1], interpolation=cv2.INTER_AREA)
    alfa = moldura[..., 3:].astype(np.uint16)
    return ((img * (255 - alfa) + moldura[..., :3] * alfa + 127) // 255).astype(np.uint8)


def processar(jpeg, preset="natural", molduras=None, qualidade=92):
    """Bytes do original → bytes do JPEG final (tratado + molduras/<largura>x<altura>.png)."""
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("imagem inválida")
    if preset not in PRESETS:
        raise ValueError(f"preset desconhecido: {preset}")
    img = PRESETS[preset][1](img, rostos(img))
    if molduras:
        img = aplicar_moldura(img, Path(molduras) / f"{img.shape[1]}x{img.shape[0]}.png")
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(qualidade)])[1].tobytes()


if __name__ == "__main__":
    import time

    # Auto-teste: cena escura e azulada deve sair mais clara e mais neutra em todos os presets.
    rng = np.random.default_rng(0)
    teste = np.clip(rng.normal((70, 45, 35), 12, (720, 1280, 3)), 0, 255).astype(np.uint8)
    for nome, (_, funcao) in PRESETS.items():
        saida = funcao(teste, [(500, 200, 200, 200)])
        assert saida.shape == teste.shape and saida.dtype == np.uint8, nome
        if nome != "original":
            assert saida.mean() > teste.mean(), f"{nome} não clareou"
    b, g, r = balanco_branco(teste).reshape(-1, 3).mean(0)
    assert abs(b - r) < abs(70 - 35), "balanço de branco não neutralizou"
    import tempfile

    pasta = Path(tempfile.mkdtemp())
    preta = np.dstack([np.zeros((720, 1280, 3), np.uint8), np.full((720, 1280), 255, np.uint8)])
    cv2.imwrite(str(pasta / "1280x720.png"), preta)
    final = cv2.imdecode(np.frombuffer(processar(cv2.imencode(".jpg", teste)[1].tobytes(), "original", pasta), np.uint8), 1)
    assert final.max() < 10, "moldura opaca preta deveria cobrir tudo"
    print("auto-teste ok")

    for arquivo in sys.argv[1:]:  # gera arquivo.<preset>.jpg para comparar
        original = Path(arquivo).read_bytes()
        for nome in PRESETS:
            inicio = time.perf_counter()
            Path(arquivo).with_suffix(f".{nome}.jpg").write_bytes(processar(original, nome))
            print(f"{arquivo} {nome}: {time.perf_counter() - inicio:.2f}s")
