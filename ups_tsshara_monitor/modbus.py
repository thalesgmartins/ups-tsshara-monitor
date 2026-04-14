"""Decodifica um frame Modbus ASCII."""

import struct
import time
import logging
import serial


_LOGGER = logging.getLogger(__name__)


def lrc(data: bytes) -> int:
    """
    Inverte a soma de todos bytes da mensagem.

    Funciona como um selo de garantia, que garante que a mensagem
    foi recebida com integridade.
    """
    return ((~sum(data) + 1) & 0xFF)


def build_request(slave: int, func: int, reg: int, count: int) -> bytes:
    """

    """
    body = bytes([slave, func]) + struct.pack(">HH", reg, count)
    checksum = lrc(body)
    frame = body.hex().upper() + f"{checksum:02X}"
    return f":{frame}\r\n".encode()


def parse_response(raw: bytes) -> list[int] | None:
    """
    Resposta Modbus ASCII: :LLFFNNDDDD...CC\r\n
    LL=slave FF=func NN=byte_count DD=dados CC=LRC
    Retorna lista de registradores (uint16) ou None em caso de erro.
    """
    try:
        text = raw.decode("ascii", errors="ignore").strip()
        if not text.startswith(":"):
            return None
        hex_data = text[1:]           # remove ':'
        raw_bytes = bytes.fromhex(hex_data)
        # último byte é LRC — verificar
        payload   = raw_bytes[:-1]
        received_lrc = raw_bytes[-1]
        if lrc(payload) != received_lrc:
            _LOGGER.warning("LRC inválido na resposta")
            # continua mesmo assim — alguns firmwares têm LRC errado
        func      = payload[1]
        if func & 0x80:               # erro Modbus
            _LOGGER.warning(f"Erro Modbus: código {payload[2]:#04x}")
            return None
        byte_count = payload[2]
        data_bytes = payload[3:3 + byte_count]
        regs = []
        for i in range(0, len(data_bytes), 2):
            regs.append(struct.unpack(">H", data_bytes[i:i+2])[0])
        return regs
    except Exception as e:
        _LOGGER.debug(f"Erro ao parsear resposta: {e}  raw={raw!r}")
        return None


def read_registers(ser: serial.Serial, slave: int, reg: int, count: int) -> list[int] | None:
    """
    Faz a leitura dos registradores do Nobreak
    """
    req = build_request(slave, 0x03, reg, count)

    # Limpamos o buffer serial pra não ler lixo antigo
    ser.reset_input_buffer()


    ser.write(req)
    ser.flush()
    
    time.sleep(0.3)
    raw = ser.read(ser.in_waiting or 128)
    if not raw:
        return None
    return parse_response(raw)
