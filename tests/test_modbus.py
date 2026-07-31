"""Testes das funções puras de protocolo Modbus ASCII."""

import pytest

from ups_tsshara_monitor import modbus


# ---------------------------------------------------------------------------
# lrc: vetores conhecidos (regressão pura, sem depender de outra função)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "data, esperado",
    [
        (bytes([0x01, 0x03, 0x00, 0x07, 0x00, 0x10]), 0xE5),
        (bytes([0x00]), 0x00),
        (bytes([0xFF]), 0x01),
    ],
)
def test_lrc_vetores_conhecidos(data, esperado):
    assert modbus.lrc(data) == esperado


def test_lrc_e_complemento_de_dois_da_soma():
    # Propriedade: (soma + lrc) deve fechar em 0 no byte baixo.
    data = bytes([0x11, 0x22, 0x33, 0x44])
    assert (sum(data) + modbus.lrc(data)) & 0xFF == 0


# ---------------------------------------------------------------------------
# build_request: frame ASCII exato (regressão), incluindo delimitadores
# ---------------------------------------------------------------------------
def test_build_request_frame_exato():
    frame = modbus.build_request(slave=1, func=0x03, reg=0x0007, count=16)
    assert frame == b":010300070010E5\r\n"


def test_build_request_sempre_delimitado():
    frame = modbus.build_request(1, 0x03, 0x0032, 10)
    assert frame.startswith(b":")
    assert frame.endswith(b"\r\n")


# ---------------------------------------------------------------------------
# parse_response: round-trip usando o próprio lrc do módulo (sem cálculo à mão)
# ---------------------------------------------------------------------------
def _frame_valido(slave: int, func: int, regs: list[int]) -> bytes:
    """Monta uma resposta Modbus ASCII válida a partir de uma lista de uint16."""
    body = bytes([slave, func, len(regs) * 2])
    for r in regs:
        body += r.to_bytes(2, "big")
    checksum = modbus.lrc(body)
    return b":" + (body.hex().upper() + f"{checksum:02X}").encode() + b"\r\n"


def test_parse_response_round_trip():
    regs = [6000, 2215, 138, 98]
    frame = _frame_valido(slave=1, func=0x03, regs=regs)
    assert modbus.parse_response(frame) == regs


def test_parse_response_sem_prefixo_retorna_none():
    assert modbus.parse_response(b"010300070010E5\r\n") is None


def test_parse_response_erro_modbus_retorna_none():
    # func com bit 0x80 = resposta de exceção
    body = bytes([0x01, 0x83, 0x02])
    frame = b":" + (body.hex().upper() + f"{modbus.lrc(body):02X}").encode() + b"\r\n"
    assert modbus.parse_response(frame) is None


def test_parse_response_lrc_errado_ainda_parseia():
    # Comportamento intencional: firmware manda LRC errado, seguimos processando.
    regs = [6000]
    body = bytes([1, 3, 2]) + (6000).to_bytes(2, "big")
    lrc_errado = (modbus.lrc(body) ^ 0xFF) & 0xFF  # corrompe de propósito
    frame = b":" + (body.hex().upper() + f"{lrc_errado:02X}").encode() + b"\r\n"
    assert modbus.parse_response(frame) == regs


def test_parse_response_lixo_retorna_none():
    assert modbus.parse_response(b"") is None
    assert modbus.parse_response(b":ZZZZ\r\n") is None
