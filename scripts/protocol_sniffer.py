#!/usr/bin/env python3
"""
PASSO 1 — Sniffer passivo: rode ENQUANTO o UPS Power MTR está aberto.
           Captura tudo que trafega e decodifica as mensagens Modbus ASCII.

PASSO 2 — Varredura: descobre quais registradores respondem (rode SEM o UPS Power MTR).

Uso:
    python3 sniffer.py --sniff      # escuta por 60s enquanto o software oficial lê
    python3 sniffer.py --scan       # varre todos os registradores 0x0000–0x00FF
    python3 sniffer.py --raw        # dump hexadecimal bruto de tudo que chega
"""

import serial
import time
import struct
import argparse
import sys
from datetime import datetime

PORT     = "/dev/ttyUSB0"
BAUD     = 9600
SLAVE_ID = 1

SEP = "─" * 64

# ══════════════════════════════════════════════════════════════════════════════
# Modbus ASCII helpers
# ══════════════════════════════════════════════════════════════════════════════

def lrc(data: bytes) -> int:
    return ((~sum(data) + 1) & 0xFF)

def build_request(slave, func, reg, count):
    body = bytes([slave, func]) + struct.pack(">HH", reg, count)
    cs   = lrc(body)
    frame = body.hex().upper() + f"{cs:02X}"
    return f":{frame}\r\n".encode()

def decode_ascii_frame(raw: bytes) -> dict | None:
    """Tenta decodificar um frame Modbus ASCII completo."""
    try:
        text = raw.decode("ascii", errors="ignore").strip()
        if not text.startswith(":"):
            return None
        hex_str   = text[1:]
        raw_bytes = bytes.fromhex(hex_str)
        payload   = raw_bytes[:-1]
        recv_lrc  = raw_bytes[-1]
        calc_lrc  = lrc(payload)

        slave = payload[0]
        func  = payload[1]

        result = {
            "slave": slave,
            "func":  func,
            "lrc_ok": recv_lrc == calc_lrc,
            "raw": text,
        }

        if func & 0x80:   # resposta de erro
            result["error_code"] = payload[2] if len(payload) > 2 else "?"
            result["type"] = "ERROR"
            return result

        if func == 0x03:  # Read Holding Registers
            if len(payload) > 2:
                byte_count = payload[2]
                data_bytes = payload[3:3 + byte_count]
                regs = []
                for i in range(0, len(data_bytes) - 1, 2):
                    regs.append(struct.unpack(">H", data_bytes[i:i+2])[0])
                result["type"]      = "RESPONSE"
                result["registers"] = regs
            else:
                # É um request (só tem endereço e contagem)
                reg   = struct.unpack(">H", payload[2:4])[0]
                count = struct.unpack(">H", payload[4:6])[0]
                result["type"]      = "REQUEST"
                result["start_reg"] = reg
                result["count"]     = count
        return result
    except Exception as e:
        return {"type": "PARSE_ERROR", "raw": repr(raw), "error": str(e)}

def open_port(timeout=2):
    s = serial.Serial()
    s.port     = PORT
    s.baudrate = BAUD
    s.bytesize = serial.EIGHTBITS
    s.parity   = serial.PARITY_NONE
    s.stopbits = serial.STOPBITS_ONE
    s.timeout  = timeout
    s.rtscts   = False
    s.xonxoff  = False
    s.open()
    time.sleep(0.1)
    s.dtr = True
    s.rts = True
    time.sleep(0.2)
    s.reset_input_buffer()
    return s

# ══════════════════════════════════════════════════════════════════════════════
# MODO 1 — Sniffer passivo
# ══════════════════════════════════════════════════════════════════════════════

def sniff(duration=90):
    print(SEP)
    print(f"SNIFFER PASSIVO — {duration}s  (abra o UPS Power MTR agora!)")
    print("Capturando tudo que o software oficial envia/recebe...")
    print(SEP)

    s = open_port(timeout=0.5)
    end = time.time() + duration
    buf = b""
    last_regs = {}   # reg_base → [valores]

    while time.time() < end:
        chunk = s.read(256)
        if not chunk:
            if buf:
                # tenta processar o que tem
                for line in buf.split(b"\n"):
                    line = line.strip()
                    if line.startswith(b":"):
                        _process_sniff_line(line + b"\r\n", last_regs)
                buf = b""
            continue
        buf += chunk

        # processa frames completos (terminam em \r\n)
        while b"\n" in buf:
            frame, buf = buf.split(b"\n", 1)
            frame = frame.strip()
            if frame.startswith(b":"):
                _process_sniff_line(frame + b"\r\n", last_regs)

    s.close()
    print()
    print(SEP)
    print("RESUMO DOS REGISTRADORES OBSERVADOS:")
    print(SEP)
    for reg in sorted(last_regs.keys()):
        vals = last_regs[reg]
        print(f"  Reg {reg:#06x} ({reg:5d}): {vals}")
    print()
    print("Cole esses endereços no arquivo ups_tsshara.py → REG_MAP")

def _process_sniff_line(raw, last_regs):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    decoded = decode_ascii_frame(raw)
    if not decoded:
        return

    t = decoded.get("type", "?")
    lrc_mark = "✓" if decoded.get("lrc_ok", True) else "✗LRC"

    if t == "REQUEST":
        reg   = decoded["start_reg"]
        count = decoded["count"]
        print(f"  {ts}  → REQUEST  slave={decoded['slave']}  reg={reg:#06x}  count={count}  {lrc_mark}")

    elif t == "RESPONSE":
        regs = decoded["registers"]
        print(f"  {ts}  ← RESP    {len(regs)} regs: {regs}  {lrc_mark}")
        # tenta descobrir qual reg base gerou essa resposta
        # (sniffer passivo não sabe o endereço da resposta, só do request)
        # Registra sequencialmente
        key = f"resp_{len(last_regs)}"
        last_regs[key] = regs

    elif t == "ERROR":
        print(f"  {ts}  ✗ ERRO Modbus  code={decoded.get('error_code')}")

    elif t == "PARSE_ERROR":
        raw_str = decoded.get("raw", "")
        print(f"  {ts}  ? RAW: {raw_str[:60]}")


# ══════════════════════════════════════════════════════════════════════════════
# MODO 2 — Varredura de registradores
# ══════════════════════════════════════════════════════════════════════════════

def scan(start=0x0000, end_reg=0x00FF, block=5):
    """Varre registradores em blocos e mostra os que respondem."""
    print(SEP)
    print(f"VARREDURA: reg {start:#06x} → {end_reg:#06x}  bloco={block}")
    print("(feche o UPS Power MTR antes de rodar isso)")
    print(SEP)

    s = open_port(timeout=1.5)
    found = {}

    reg = start
    while reg <= end_reg:
        count = min(block, end_reg - reg + 1)
        req   = build_request(SLAVE_ID, 0x03, reg, count)

        s.reset_input_buffer()
        s.write(req)
        s.flush()
        time.sleep(0.4)
        raw = s.read(s.in_waiting or 128)

        if raw:
            decoded = decode_ascii_frame(raw)
            if decoded and decoded.get("type") == "RESPONSE":
                regs = decoded["registers"]
                print(f"  ✓ reg {reg:#06x} ({reg:4d}): {regs}  (LRC {'✓' if decoded['lrc_ok'] else '✗'})")
                for i, val in enumerate(regs):
                    found[reg + i] = val
            elif decoded and decoded.get("type") == "ERROR":
                print(f"  ✗ reg {reg:#06x}: erro Modbus {decoded.get('error_code')}")
            else:
                # resposta existe mas não parseou — mostra raw
                raw_str = " ".join(f"{b:02X}" for b in raw)
                print(f"  ? reg {reg:#06x}: raw [{raw_str}]")
        else:
            sys.stdout.write(".")
            sys.stdout.flush()

        reg += count

    s.close()
    print()
    print()
    print(SEP)
    print("REGISTRADORES COM RESPOSTA:")
    print(SEP)
    for r in sorted(found.keys()):
        v = found[r]
        # tenta interpretar como signed e como valor /10
        signed = v if v <= 32767 else v - 65536
        print(f"  Reg {r:#06x} ({r:5d}):  raw={v:6d}  signed={signed:6d}  /10={signed/10:8.1f}  /100={signed/100:6.2f}")

    print()
    print("Interprete os valores comparando com o que o UPS Power MTR mostra")
    print("(tensão de entrada, saída, % bateria, % carga, temperatura...)")
    return found


# ══════════════════════════════════════════════════════════════════════════════
# MODO 3 — Dump raw
# ══════════════════════════════════════════════════════════════════════════════

def raw_dump(duration=30):
    print(SEP)
    print(f"DUMP RAW — {duration}s  (qualquer coisa que chegar na porta)")
    print(SEP)
    s = open_port(timeout=0.3)
    end = time.time() + duration
    while time.time() < end:
        chunk = s.read(256)
        if chunk:
            ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            try:
                ascii_str = chunk.decode("ascii", errors="replace").replace("\r","\\r").replace("\n","\\n")
            except:
                ascii_str = "?"
            print(f"  {ts}  [{hex_str}]")
            print(f"          ascii: {ascii_str!r}")
        else:
            sys.stdout.write(".")
            sys.stdout.flush()
    s.close()
    print()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sniff",    action="store_true", help="Sniffer passivo (rode com UPS Power MTR aberto)")
    parser.add_argument("--scan",     action="store_true", help="Varre registradores 0x0000-0x00FF")
    parser.add_argument("--scan-ext", action="store_true", help="Varre faixa extendida 0x0000-0x03FF")
    parser.add_argument("--raw",      action="store_true", help="Dump hexadecimal bruto")
    parser.add_argument("--duration", type=int, default=90, help="Duração do sniff em segundos (default 90)")
    args = parser.parse_args()

    if args.sniff:
        sniff(args.duration)
    elif args.scan:
        scan(0x0000, 0x00FF)
    elif args.scan_ext:
        scan(0x0000, 0x03FF)
    elif args.raw:
        raw_dump(args.duration)
    else:
        print("Use --sniff, --scan, --scan-ext ou --raw")
        print()
        print("Fluxo recomendado:")
        print("  1. Feche o UPS Power MTR")
        print("  2. python3 sniffer.py --scan       ← descobre os registradores")
        print("  3. Abra o UPS Power MTR")
        print("  4. python3 sniffer.py --sniff      ← captura o protocolo real")
        print("  5. Compare os valores raw com o que o software mostra")