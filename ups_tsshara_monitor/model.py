"""Contrato normalizado: o que uma leitura de nobreak É, independente de fonte/saída."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UpsReading:
    values: dict  # {"input_voltage": 221.5, "battery_charge": 100.0, ...}
    status: dict  # {"utility_fail": False, "battery_low": False, ...}
    online: bool
    timestamp: str

    def get(self, key, default=None):
        return self.values.get(key, default)
