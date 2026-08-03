import logging
import time
from collections.abc import Callable
from datetime import datetime

import serial

from . import config, modbus, registers
from .model import UpsReading

_LOGGER = logging.getLogger(__name__)


def open_serial() -> serial.Serial:
    s = serial.Serial()
    s.port = config.PORT
    s.baudrate = config.BAUD
    s.bytesize = serial.EIGHTBITS
    s.parity = serial.PARITY_NONE
    s.stopbits = serial.STOPBITS_ONE
    s.timeout = 2
    s.rtscts = False
    s.xonxoff = False
    s.open()
    time.sleep(0.1)
    s.dtr = True
    s.rts = True
    time.sleep(0.2)
    return s


def read_once(ser) -> UpsReading:
    """Lê todos os blocos uma vez e devolve um UpsReading (values + status)."""
    values = {}
    ok = False
    for base_reg, count, section, fields in registers.REG_MAP:
        regs = modbus.read_registers(ser, config.SLAVE_ID, base_reg, count)
        if regs:
            ok = True
            for offset, name, divisor, _unit in fields:
                if offset < len(regs):
                    raw_val = regs[offset]
                    if raw_val > 32767:
                        raw_val -= 65536
                    values[name] = round(raw_val / divisor, 2)
        else:
            _LOGGER.warning(f"Sem resposta no bloco {section} (reg {base_reg:#06x})")

    status = {}
    if "ups_status_word" in values:
        status = registers.decode_status(int(values["ups_status_word"]))

    # --- TRAVA DE SOFTWARE PARA STATUS FLUTUANTE ---
    input_v = values.get("input_voltage", 0)
    bat_pct = values.get("battery_charge", 0)
    if input_v > 180.0:
        status["utility_fail"] = False
    elif input_v < 100.0:
        status["utility_fail"] = True
    if bat_pct > 30.0:
        status["battery_low"] = False
    elif bat_pct <= 20.0:
        status["battery_low"] = True

    return UpsReading(values=values, status=status, online=ok, timestamp=datetime.now().isoformat())


def poll_loop(on_reading: Callable[[UpsReading], None]):
    """Laço de leitura. A cada ciclo entrega um UpsReading ao callback on_reading."""
    _LOGGER.info(f"Iniciando Serial: {config.PORT} {config.BAUD} 8N1 slave={config.SLAVE_ID}")
    while True:
        try:
            with open_serial() as ser:
                while True:
                    reading = read_once(ser)
                    on_reading(reading)

                    if reading.online:
                        v = reading.values
                        estado = "ON_BATTERY" if reading.status.get("utility_fail") else "ONLINE"
                        _LOGGER.info(
                            f"Vin={v.get('input_voltage', '?')}V  "
                            f"Iin={v.get('input_current', '?')}A  "
                            f"Vout={v.get('output_voltage', '?')}V  "
                            f"Iout={v.get('output_current', '?')}A  "
                            f"Load={v.get('output_load', '?')}%  "
                            f"P={v.get('output_power', '?')}kW  "
                            f"S={v.get('output_apparent', '?')}kVA  "
                            f"Bat={v.get('battery_charge', '?')}%  "
                            f"Vbat={v.get('battery_voltage', '?')}V  "
                            f"Temp={v.get('temperature', '?')}°C  "
                            f"Status={estado}"
                        )

                    time.sleep(config.POLL_SECS)

        except serial.SerialException as e:
            _LOGGER.error(f"Erro serial: {e} — tentando novamente em 10s")
            time.sleep(10)
        except Exception as e:
            _LOGGER.exception(f"Erro inesperado: {e}")
            time.sleep(10)
