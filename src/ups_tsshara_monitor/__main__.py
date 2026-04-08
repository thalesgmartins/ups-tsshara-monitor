#!/usr/bin/env python3
"""
Tsshara UPS SYAL IN — Modbus ASCII 9600 7E1 slave=1
Lê registradores, expõe via NUT-like TCP e MQTT (Home Assistant).

Dependências:
    pip install pyserial paho-mqtt

Uso:
    python3 ups_tsshara.py              # apenas leitura/log
    python3 ups_tsshara.py --server     # + servidor TCP estilo NUT
    python3 ups_tsshara.py --mqtt       # + publicação MQTT
    python3 ups_tsshara.py --server --mqtt  # tudo junto
"""

import serial
import time
import struct
import argparse
import threading
import socket
import json
import logging
from datetime import datetime

# ─── CONFIGURAÇÃO ────────────────────────────────────────────────────────────
PORT        = "/dev/ttyUSB0"
BAUD        = 9600
SLAVE_ID    = 1
POLL_SECS   = 5

# Servidor TCP
TCP_HOST    = "0.0.0.0"
TCP_PORT    = 3493

# MQTT
MQTT_HOST   = "192.168.1.60"
MQTT_PORT   = 1883
MQTT_USER   = "thales"
MQTT_PASS   = "Arduinagem2025!"
MQTT_PREFIX = "homeassistant/sensor/ups"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ups")

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
            log.warning("LRC inválido na resposta")
            # continua mesmo assim — alguns firmwares têm LRC errado
        func      = payload[1]
        if func & 0x80:               # erro Modbus
            log.warning(f"Erro Modbus: código {payload[2]:#04x}")
            return None
        byte_count = payload[2]
        data_bytes = payload[3:3 + byte_count]
        regs = []
        for i in range(0, len(data_bytes), 2):
            regs.append(struct.unpack(">H", data_bytes[i:i+2])[0])
        return regs
    except Exception as e:
        log.debug(f"Erro ao parsear resposta: {e}  raw={raw!r}")
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
# MAPA DE REGISTRADORES
# Baseado no protocolo padrão de UPS industriais Modbus ASCII (tipo 31/1 TX)
# Ajuste os endereços se os valores não fizerem sentido.
# ══════════════════════════════════════════════════════════════════════════════

#  (endereço_base, quantidade, descrição, lista de campos)
#  Cada campo: (offset_no_bloco, nome, divisor, unidade)

REG_MAP = [
    (0x0007, 4, "Freq_Bat", [
        (0, "output_frequency", 100, "Hz"), # 6003 -> 60.03Hz
        (3, "battery_charge",    1, "%"),  # 100 -> 100%
    ]),
    (0x000D, 1, "Saida", [
        (0, "output_voltage",   10, "V"),  # 2219 -> 221.9V
    ]),
    (0x0016, 1, "Carga", [
        (0, "output_load",      10, "%"),  # 98 -> 9.8%
    ]),
    (0x0019, 4, "Rede_Temp", [
        (0, "input_voltage",    10, "V"),  # 2200 -> 220.0V
        (3, "temperature",      10, "°C"), # 250 -> 25.0°C
    ]),
    (0x0032, 1, "Bateria_V", [
        (0, "battery_voltage",  10, "V"),  # 2169 -> 216.9V
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
    log.info(f"Iniciando leitura: {PORT} {BAUD} 7E1 slave={SLAVE_ID}")
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
                            log.debug(f"  [{section}] {regs}")
                        else:
                            log.warning(f"Sem resposta para bloco {section} (reg {base_reg:#06x})")

                    if "ups_status_word" in data:
                        data.update(decode_status(int(data["ups_status_word"])))

                    data["timestamp"] = datetime.now().isoformat()
                    data["online"] = ok

                    with _state_lock:
                        _state.clear()
                        _state.update(data)

                    if ok:
                        log.info(
                            f"Vin={data.get('input_voltage','?')}V  "
                            f"Vout={data.get('output_voltage','?')}V  "
                            f"Bat={data.get('battery_charge','?')}%  "
                            f"Load={data.get('output_load','?')}%  "
                            f"Runtime={data.get('battery_runtime','?')}min  "
                            f"Status={'ON_BATTERY' if data.get('utility_fail') else 'ONLINE'}"
                        )
                    time.sleep(POLL_SECS)

        except serial.SerialException as e:
            log.error(f"Erro serial: {e} — tentando novamente em 10s")
            time.sleep(10)
        except Exception as e:
            log.exception(f"Erro inesperado: {e}")
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
    ("input_voltage",    "Tensão Entrada",   "V",   "voltage",      "mdi:flash"),
    ("output_voltage",   "Tensão Saída",     "V",   "voltage",      "mdi:flash"),
    ("output_load",      "Carga",            "%",   "power_factor", "mdi:gauge"),
    ("battery_charge",   "Bateria",          "%",   "battery",      "mdi:battery"),
    ("battery_voltage",  "Tensão Bateria",   "V",   "voltage",      "mdi:battery"),
    ("battery_runtime",  "Autonomia",        "min", None,           "mdi:timer"),
    ("input_frequency",  "Frequência",       "Hz",  "frequency",    "mdi:sine-wave"),
    ("temperature",      "Temperatura",      "°C",  "temperature",  "mdi:thermometer"),
    ("output_power",     "Potência Saída",   "W",   "power",        "mdi:lightning-bolt"),
]

def mqtt_loop():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(client_id="ups_tsshara")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            log.info(f"[MQTT] Conectado ao broker {MQTT_HOST}:{MQTT_PORT}")
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
            log.error(f"[MQTT] Falha na conexão: rc={rc}")

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
        log.debug("[MQTT] Publicado")


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

    log.info("Rodando. Ctrl+C para sair.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Encerrando.")

if __name__ == "__main__":
    main()