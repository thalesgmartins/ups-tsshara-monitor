import time
import logging
import serial
from datetime import datetime

from . import config
from . import modbus
from . import registers

_LOGGER = logging.getLogger(__name__)

def open_serial() -> serial.Serial:
    s = serial.Serial()
    s.port     = config.PORT
    s.baudrate = config.BAUD
    s.bytesize = serial.EIGHTBITS
    s.parity   = serial.PARITY_NONE
    s.stopbits = serial.STOPBITS_ONE
    s.timeout  = 2
    s.rtscts   = False
    s.xonxoff  = False
    s.open()
    time.sleep(0.1)
    s.dtr = True
    s.rts = True
    time.sleep(0.2)
    return s

def poll_loop(shared_state: dict, state_lock):
    _LOGGER.info(f"Iniciando Serial: {config.PORT} {config.BAUD} 8N1 slave={config.SLAVE_ID}")
    while True:
        try:
            with open_serial() as ser:
                while True:
                    data = {}
                    ok = False
                    for base_reg, count, section, fields in registers.REG_MAP:
                        regs = modbus.read_registers(ser, config.SLAVE_ID, base_reg, count)
                        if regs:
                            ok = True
                            for offset, name, divisor, unit in fields:
                                if offset < len(regs):
                                    raw_val = regs[offset]
                                    if raw_val > 32767: raw_val -= 65536
                                    data[name] = round(raw_val / divisor, 2)
                        else:
                            _LOGGER.warning(f"Sem resposta no bloco {section} (reg {base_reg:#06x})")

                    if "ups_status_word" in data:
                        data.update(registers.decode_status(int(data["ups_status_word"])))

                    data["timestamp"] = datetime.now().isoformat()
                    data["online"] = ok

                    # Atualiza a memória global em segurança
                    with state_lock:
                        shared_state.clear()
                        shared_state.update(data)

                    if ok:
                        _LOGGER.info(
                            f"Vin={data.get('input_voltage','?')}V  "
                            f"Iin={data.get('input_current','?')}A  "
                            f"Vout={data.get('output_voltage','?')}V  "
                            f"Iout={data.get('output_current','?')}A  "
                            f"Load={data.get('output_load','?')}%  "
                            f"P={data.get('output_power','?')}kW  "
                            f"S={data.get('output_apparent','?')}kVA  "
                            f"Bat={data.get('battery_charge','?')}%  "
                            f"Vbat={data.get('battery_voltage','?')}V  "
                            f"Temp={data.get('temperature','?')}°C  "
                            f"Status={'ON_BATTERY' if data.get('utility_fail') else 'ONLINE'}"
                        )
                    
                    time.sleep(config.POLL_SECS)

        except serial.SerialException as e:
            _LOGGER.error(f"Erro serial: {e} — tentando novamente em 10s")
            time.sleep(10)
        except Exception as e:
            _LOGGER.exception(f"Erro inesperado: {e}")
            time.sleep(10)