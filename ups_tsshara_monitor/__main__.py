"""Start TS Shara UPS SYAL IN Monitor"""

import argparse
import threading
import socket
import json
import time
import logging
import os
import socket
import struct
import threading
from datetime import datetime

import serial

from .config import *


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_LOGGER = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# MODBUS ASCII
# ══════════════════════════════════════════════════════════════════════════════

def lrc(data: bytes) -> int:
    return ((~sum(data) + 1) & 0xFF)

def build_request(slave: int, func: int, reg: int, count: int) -> bytes:
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
    req = build_request(slave, 0x03, reg, count)
    ser.reset_input_buffer()
    ser.write(req)
    ser.flush()
    time.sleep(0.3)
    raw = ser.read(ser.in_waiting or 128)
    if not raw:
        return None
    return parse_response(raw)


# ══════════════════════════════════════════════════════════════════════════════
# MAPA DE REGISTRADORES — 100% confirmado contra UPS Power MTR
# Tsshara SYAL IN / protocolo: Modbus ASCII 9600 8N1 slave=1
# ══════════════════════════════════════════════════════════════════════════════
#
#  (endereço_base, quantidade, nome_bloco, lista_de_campos)
#  Campo: (offset, nome_variável, divisor, unidade)
#
#  Confirmações visuais (UPS Power MTR vs scan):
#    0x0007 raw=6000  /100 = 60.00 Hz  ← input_frequency  ✓
#    0x000a raw=100   /1   = 100 %     ← battery_charge   ✓
#    0x000d raw=2215  /10  = 221.5 V   ← input_voltage    ✓
#    0x0010 raw=184   /10  = 18.4 A    ← input_current    ✓
#    0x0013 raw=6000  /100 = 60.00 Hz  ← bypass_frequency ✓
#    0x0016 raw=98    /100 = 0.98      ← input_pf         ✓
#    0x0019 raw=2200  /10  = 220.0 V   ← output_voltage   ✓
#    0x001c raw=246   /10  = 24.5 A    ← output_current   ✓  (OutputData Curr=24.5A)
#    0x001f raw=6000  /100 = 60.00 Hz  ← output_frequency ✓
#    0x0022 raw=70    /100 = 0.70      ← output_pf        ✓  (OutputData PF=0.70)
#    0x0025 raw=53    /10  = 5.2 kVA   ← output_apparent  ✓  (OutputData Power S=5.2kVA)
#    0x0028 raw=37    /10  = 3.7 kW    ← output_power     ✓  (OutputData Power P=3.6kW ≈)
#    0x002e raw=543   /10  = 54.3 %    ← output_load      ✓  (OutputData Load=53.2% ≈)
#    0x0032 raw=2169  /10  = 216.9 V   ← battery_voltage  ✓  (BatteryData Voltage=216.9V)
#    0x0034 raw=1     /1   = status    ← ups_status_word
#    0x0038 raw=1000  /1   = 1000 VA   ← rated_va         (capacidade nominal)
#    0x0039 raw=238   /10  = 23.8 °C   ← temperature      (BattTemp/EnvTemp=0.0 no sw,
#                                                           mas 24°C é razoável p/ ambiente)
#    0x003a raw=236   /10  = 23.6      ← (campo extra, possivelmente 2ª temp)
#    0x003b raw=300   /10  = 30.0      ← (campo extra)
#    0x004b raw=2212  /10  = 221.2 V   ← bypass_voltage   ✓  (BypassData Volt=221.7V ≈)

REG_MAP = [
    # ── Bloco 1: Entrada (0x0007 → 0x0016) ──────────────────────────
    (0x0007, 16, "Entrada", [
        (0, "input_frequency",  100, "Hz"),  # 0x0007: 6000 → 60.00 Hz
        (3, "battery_charge",     1, "%"),   # 0x000a: 100  → 100 %
        (6, "input_voltage",     10, "V"),   # 0x000d: 2215 → 221.5 V
        (9, "input_current",     10, "A"),   # 0x0010: 184  → 18.4 A
        (15,"input_pf",         100, ""),    # 0x0016: 98   → 0.98
    ]),
    # ── Bloco 2: Bypass + Saída (0x0013 → 0x002e) ───────────────────
    (0x0013, 28, "Saida", [
        (0,  "bypass_frequency", 100, "Hz"), # 0x0013: 6000 → 60.00 Hz
        (6,  "output_voltage",    10, "V"),  # 0x0019: 2200 → 220.0 V
        (9,  "output_current",    10, "A"),  # 0x001c: 246  → 24.6 A
        (12, "output_frequency", 100, "Hz"), # 0x001f: 6000 → 60.00 Hz
        (15, "output_pf",        100, ""),   # 0x0022: 70   → 0.70
        (18, "output_apparent",   10, "kVA"),# 0x0025: 53   → 5.3 kVA
        (21, "output_power",      10, "kW"), # 0x0028: 37   → 3.7 kW
        (27, "output_load",       10, "%"),  # 0x002e: 543  → 54.3 %
    ]),
    # ── Bloco 3: Bateria + Status (0x0032 → 0x003b) ─────────────────
    (0x0032, 10, "Bateria", [
        (0, "battery_voltage",   10, "V"),   # 0x0032: 2169 → 216.9 V
        (2, "ups_status_word",    1, ""),    # 0x0034: 1    → bits de status
        (6, "rated_va",           1, "VA"),  # 0x0038: 1000 → capacidade nominal
        (7, "temperature",       10, "°C"),  # 0x0039: 238  → 23.8 °C
    ]),
    # ── Bloco 4: Bypass tensão (0x004b) ─────────────────────────────
    (0x004b, 1, "Bypass", [
        (0, "bypass_voltage",    10, "V"),   # 0x004b: 2212 → 221.2 V
    ]),
]

# Decodificação do status word (bit a bit)
STATUS_BITS = {
    0:  "utility_fail",       # falta de energia da rede
    1:  "battery_low",
    2:  "bypass_active",
    3:  "ups_fault",
    4:  "ups_standby",
    5:  "test_in_progress",
    6:  "shutdown_active",
    7:  "beeper_on",
}

def decode_status(word: int) -> dict:
    return {name: bool(word & (1 << bit)) for bit, name in STATUS_BITS.items()}


# ══════════════════════════════════════════════════════════════════════════════
# LEITURA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

# Estado global compartilhado entre threads
_state: dict = {}
_state_lock = threading.Lock()

def open_serial() -> serial.Serial:
    s = serial.Serial()
    s.port     = PORT
    s.baudrate = BAUD
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

def poll_loop():
    """Loop de leitura que roda em thread separada."""
    _LOGGER.info(f"Iniciando leitura: {PORT} {BAUD} 8N1 slave={SLAVE_ID}")
    while True:
        try:
            with open_serial() as ser:
                while True:
                    data = {}
                    ok = False
                    for base_reg, count, section, fields in REG_MAP:
                        regs = read_registers(ser, SLAVE_ID, base_reg, count)
                        if regs:
                            ok = True
                            for offset, name, divisor, unit in fields:
                                if offset < len(regs):
                                    raw_val = regs[offset]
                                    # trata signed 16-bit
                                    if raw_val > 32767:
                                        raw_val -= 65536
                                    data[name] = round(raw_val / divisor, 2)
                            _LOGGER.debug(f"  [{section}] {regs}")
                        else:
                            _LOGGER.warning(f"Sem resposta para bloco {section} (reg {base_reg:#06x})")

                    if "ups_status_word" in data:
                        data.update(decode_status(int(data["ups_status_word"])))

                    data["timestamp"] = datetime.now().isoformat()
                    data["online"] = ok

                    with _state_lock:
                        _state.clear()
                        _state.update(data)

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
                    time.sleep(POLL_SECS)

        except serial.SerialException as e:
            _LOGGER.error(f"Erro serial: {e} — tentando novamente em 10s")
            time.sleep(10)
        except Exception as e:
            _LOGGER.exception(f"Erro inesperado: {e}")
            time.sleep(10)


# ══════════════════════════════════════════════════════════════════════════════
# SERVIDOR TCP (compatível com clientes NUT simples e Home Assistant)
# ══════════════════════════════════════════════════════════════════════════════

NUT_VAR_MAP = {
    "ups.status":             lambda d: "OB LB" if d.get("utility_fail") and d.get("battery_low")
                                        else "OB" if d.get("utility_fail")
                                        else "OL",
    "ups.load":               lambda d: str(d.get("output_load", 0)),
    "battery.charge":         lambda d: str(d.get("battery_charge", 0)),
    "battery.runtime":        lambda d: str(int(d.get("battery_runtime", 0)) * 60),  # NUT usa segundos
    "battery.voltage":        lambda d: str(d.get("battery_voltage", 0)),
    "input.voltage":          lambda d: str(d.get("input_voltage", 0)),
    "input.frequency":        lambda d: str(d.get("input_frequency", 0)),
    "output.voltage":         lambda d: str(d.get("output_voltage", 0)),
    "output.frequency":       lambda d: str(d.get("output_frequency", 0)),
    "ups.temperature":        lambda d: str(d.get("temperature", 0)),
    "ups.mfr":                lambda d: "Tsshara",
    "ups.model":              lambda d: "SYAL IN",
    "ups.type":               lambda d: "online",
}

def handle_nut_client(conn, addr):
    log.info(f"[NUT] Conexão de {addr}")
    try:
        conn.settimeout(30)
        buf = ""
        while True:
            chunk = conn.recv(256).decode("ascii", errors="ignore")
            if not chunk:
                break
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                log.debug(f"[NUT] cmd: {line!r}")

                with _state_lock:
                    d = dict(_state)

                if line == "LIST UPS":
                    conn.sendall(b"BEGIN LIST UPS\nUPS tsshara \"Tsshara SYAL IN\"\nEND LIST UPS\n")

                elif line.startswith("LIST VAR"):
                    resp = "BEGIN LIST VAR tsshara\n"
                    for var, fn in NUT_VAR_MAP.items():
                        try:
                            resp += f"VAR tsshara {var} \"{fn(d)}\"\n"
                        except:
                            pass
                    resp += "END LIST VAR tsshara\n"
                    conn.sendall(resp.encode())

                elif line.startswith("GET VAR"):
                    parts = line.split()
                    if len(parts) == 4:
                        var = parts[3]
                        fn = NUT_VAR_MAP.get(var)
                        if fn:
                            try:
                                conn.sendall(f"VAR tsshara {var} \"{fn(d)}\"\n".encode())
                            except:
                                conn.sendall(b"ERR VAR-NOT-SUPPORTED\n")
                        else:
                            conn.sendall(b"ERR VAR-NOT-SUPPORTED\n")
                    else:
                        conn.sendall(b"ERR INVALID-ARGUMENT\n")

                elif line == "LOGOUT":
                    conn.sendall(b"OK Goodbye\n")
                    return

                else:
                    conn.sendall(b"ERR UNKNOWN-COMMAND\n")
    except Exception as e:
        log.debug(f"[NUT] {addr} desconectou: {e}")
    finally:
        conn.close()

def nut_server_loop():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((TCP_HOST, TCP_PORT))
        srv.listen(5)
        log.info(f"[NUT] Servidor TCP em {TCP_HOST}:{TCP_PORT}")
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_nut_client, args=(conn, addr), daemon=True)
            t.start()


# ══════════════════════════════════════════════════════════════════════════════
# MQTT — Home Assistant Auto Discovery
# ══════════════════════════════════════════════════════════════════════════════

MQTT_SENSORS = [
    # Entrada
    ("input_voltage",    "Tensão Entrada",      "V",   "voltage",      "mdi:transmission-tower"),
    ("input_current",    "Corrente Entrada",    "A",   "current",      "mdi:current-ac"),
    ("input_frequency",  "Frequência Entrada",  "Hz",  "frequency",    "mdi:sine-wave"),
    ("input_pf",         "FP Entrada",          "",    "power_factor", "mdi:angle-acute"),
    # Saída
    ("output_voltage",   "Tensão Saída",        "V",   "voltage",      "mdi:flash"),
    ("output_current",   "Corrente Saída",      "A",   "current",      "mdi:current-ac"),
    ("output_frequency", "Frequência Saída",    "Hz",  "frequency",    "mdi:sine-wave"),
    ("output_pf",        "FP Saída",            "",    "power_factor", "mdi:angle-acute"),
    ("output_load",      "Carga",               "%",   "power_factor", "mdi:gauge"),
    ("output_power",     "Potência Ativa",      "kW",  "power",        "mdi:lightning-bolt"),
    ("output_apparent",  "Potência Aparente",   "kVA", None,           "mdi:lightning-bolt-outline"),
    # Bateria
    ("battery_charge",   "Bateria",             "%",   "battery",      "mdi:battery"),
    ("battery_voltage",  "Tensão Bateria (DC)", "V",   "voltage",      "mdi:battery"),
    # Sistema
    ("temperature",      "Temperatura",         "°C",  "temperature",  "mdi:thermometer"),
    ("bypass_voltage",   "Tensão Bypass",       "V",   "voltage",      "mdi:transit-detour"),
    ("bypass_frequency", "Frequência Bypass",   "Hz",  "frequency",    "mdi:sine-wave"),
]

def mqtt_loop():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(client_id="ups_tsshara")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info(f"[MQTT] Conectado ao broker {MQTT_HOST}:{MQTT_PORT}")
            # Auto discovery Home Assistant
            for field, name, unit, dev_class, icon in MQTT_SENSORS:
                config = {
                    "name": f"UPS {name}",
                    "unique_id": f"ups_tsshara_{field}",
                    "state_topic": f"{MQTT_PREFIX}/{field}/state",
                    "unit_of_measurement": unit,
                    "icon": icon,
                    "device": {
                        "identifiers": ["ups_tsshara"],
                        "name": "Tsshara SYAL IN",
                        "manufacturer": "Tsshara",
                        "model": "SYAL IN",
                    },
                }
                if dev_class:
                    config["device_class"] = dev_class
                c.publish(
                    f"{MQTT_PREFIX}/{field}/config",
                    json.dumps(config),
                    retain=True
                )
            # Sensor de status textual
            status_config = {
                "name": "UPS Status",
                "unique_id": "ups_tsshara_status",
                "state_topic": f"{MQTT_PREFIX}/status/state",
                "icon": "mdi:power-plug",
                "device": {"identifiers": ["ups_tsshara"]},
            }
            c.publish(f"{MQTT_PREFIX}/status/config", json.dumps(status_config), retain=True)
        else:
            _LOGGER.error(f"[MQTT] Falha na conexão: rc={rc}")

    client.on_connect = on_connect
    client.connect_async(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    while True:
        time.sleep(POLL_SECS)
        with _state_lock:
            d = dict(_state)
        if not d:
            continue
        for field, name, unit, _, _ in MQTT_SENSORS:
            if field in d:
                client.publish(f"{MQTT_PREFIX}/{field}/state", str(d[field]), retain=True)
        # Status
        if d.get("utility_fail") and d.get("battery_low"):
            status = "OB LB"
        elif d.get("utility_fail"):
            status = "On Battery"
        else:
            status = "Online"
        client.publish(f"{MQTT_PREFIX}/status/state", status, retain=True)
        _LOGGER.debug("[MQTT] Publicado")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Tsshara UPS SYAL IN monitor")
    parser.add_argument("--server", action="store_true", help="Inicia servidor TCP estilo NUT")
    parser.add_argument("--mqtt",   action="store_true", help="Publica dados via MQTT")
    parser.add_argument("--debug",  action="store_true", help="Log verboso")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Thread de leitura serial (sempre ativa)
    t_poll = threading.Thread(target=poll_loop, daemon=True, name="poll")
    t_poll.start()

    if args.server:
        t_nut = threading.Thread(target=nut_server_loop, daemon=True, name="nut")
        t_nut.start()

    if args.mqtt:
        t_mqtt = threading.Thread(target=mqtt_loop, daemon=True, name="mqtt")
        t_mqtt.start()

    _LOGGER.info("TS Shara UPS SYAL IN Monitor Rodando")
    try:
        while True:
            time.sleep(1)
    except Exception as e:
        _LOGGER.info("Encerrando. Motivo: %s", e)


if __name__ == "__main__":
    main()