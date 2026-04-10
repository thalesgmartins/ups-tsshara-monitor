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


STATUS_BITS = {
    0:  "utility_fail",
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