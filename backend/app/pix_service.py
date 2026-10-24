"""Pix: chave da pizzaria e "copia e cola" (BR Code estático do Banco Central).

O BR Code é um texto no padrão EMV que qualquer app de banco entende: leva a chave,
o nome e a cidade de quem recebe e o valor. Não precisa de conta em provedor de
pagamento — mas também não confirma o pagamento sozinho: a pizzaria confere o
comprovante enviado pelo cliente e marca o pedido como pago.
"""
import io
import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from . import models

CHAVES_CONFIG = {"tipo": "pix_tipo", "chave": "pix_chave", "nome": "pix_nome", "cidade": "pix_cidade"}


class ChavePixInvalida(ValueError):
    pass


def normalizar_chave(tipo: str, chave: str) -> str:
    """Escreve a chave no formato que o Pix exige (ex.: telefone vira +55DDDNÚMERO)."""
    chave = chave.strip()
    digitos = re.sub(r"\D", "", chave)
    if tipo == "telefone":
        if digitos.startswith("55") and len(digitos) in (12, 13):
            digitos = digitos[2:]
        if len(digitos) not in (10, 11):
            raise ChavePixInvalida("Telefone da chave Pix deve ter DDD + número")
        return f"+55{digitos}"
    if tipo == "cpf":
        if len(digitos) != 11:
            raise ChavePixInvalida("CPF deve ter 11 dígitos")
        return digitos
    if tipo == "cnpj":
        if len(digitos) != 14:
            raise ChavePixInvalida("CNPJ deve ter 14 dígitos")
        return digitos
    if tipo == "email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", chave):
            raise ChavePixInvalida("E-mail da chave Pix inválido")
        return chave.lower()
    if tipo == "aleatoria":
        if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", chave):
            raise ChavePixInvalida("Chave aleatória deve ser o código de 32 caracteres que o banco mostra")
        return chave.lower()
    raise ChavePixInvalida("Tipo de chave inválido")


def ler_config(db: Session) -> dict:
    valores = {campo: db.get(models.Configuracao, chave) for campo, chave in CHAVES_CONFIG.items()}
    return {campo: (cfg.valor if cfg and cfg.valor else "") for campo, cfg in valores.items()}


def salvar_config(db: Session, tipo: str, chave: str, nome: str, cidade: str):
    """Grava a configuração; chave vazia desliga o Pix no site."""
    chave = normalizar_chave(tipo, chave) if chave.strip() else ""
    for campo, valor in (("tipo", tipo), ("chave", chave), ("nome", nome.strip()), ("cidade", cidade.strip())):
        cfg = db.get(models.Configuracao, CHAVES_CONFIG[campo]) or models.Configuracao(chave=CHAVES_CONFIG[campo])
        cfg.valor = valor
        db.add(cfg)


def pix_disponivel(db: Session) -> bool:
    cfg = ler_config(db)
    return bool(cfg["chave"] and cfg["nome"] and cfg["cidade"])


def _sem_acento(texto: str, limite: int) -> str:
    """O BR Code aceita só caracteres ASCII; nome até 25 e cidade até 15 caracteres."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_.split())[:limite]


def _campo(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(texto: str) -> str:
    """CRC16-CCITT (polinômio 0x1021, valor inicial 0xFFFF), exigido no campo 63."""
    crc = 0xFFFF
    for byte in texto.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def copia_e_cola(chave: str, nome: str, cidade: str, valor: Optional[float] = None, txid: str = "***") -> str:
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave.strip())
    payload = (
        _campo("00", "01")
        + _campo("26", conta)
        + _campo("52", "0000")
        + _campo("53", "986")  # real
        + (_campo("54", f"{valor:.2f}") if valor else "")
        + _campo("58", "BR")
        + _campo("59", _sem_acento(nome, 25))
        + _campo("60", _sem_acento(cidade, 15))
        + _campo("62", _campo("05", txid))
        + "6304"
    )
    return payload + _crc16(payload)


def qr_svg(texto: str) -> str:
    """QR Code em SVG (sem imagem externa: funciona offline e imprime nítido)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    saida = io.BytesIO()
    img.save(saida)
    return saida.getvalue().decode("utf-8")


def pix_do_pedido(db: Session, pedido: models.Pedido) -> dict:
    cfg = ler_config(db)
    texto = copia_e_cola(cfg["chave"], cfg["nome"], cfg["cidade"], pedido.total, txid=f"BRASA{pedido.id}")
    return {"chave": cfg["chave"], "nome": cfg["nome"], "valor": pedido.total, "copia_e_cola": texto, "qr_svg": qr_svg(texto)}
