"""Testes da lógica pura do MqttSink (sem conexão de rede)."""

import ups_tsshara_monitor.sinks  # noqa: F401  (dispara o registro dos sinks internos)
from ups_tsshara_monitor.model import UpsReading
from ups_tsshara_monitor.sinks.base import _REGISTRY
from ups_tsshara_monitor.sinks.mqtt import MqttSink


def _reading(*, utility_fail=False, battery_low=False, battery_charge=100):
    return UpsReading(
        values={"battery_charge": battery_charge},
        status={"utility_fail": utility_fail, "battery_low": battery_low},
        online=True,
        timestamp="t",
    )


def test_status_online_rede_ok_bateria_cheia():
    assert MqttSink._status_text(_reading()) == "Online"


def test_status_charging_rede_ok_bateria_incompleta():
    assert MqttSink._status_text(_reading(battery_charge=80)) == "Charging"


def test_status_on_battery_sem_rede():
    assert MqttSink._status_text(_reading(utility_fail=True)) == "On Battery"


def test_status_low_battery_sem_rede_e_bateria_baixa():
    r = _reading(utility_fail=True, battery_low=True, battery_charge=15)
    assert MqttSink._status_text(r) == "Low Battery"


def test_mqtt_registrado_no_registry():
    assert "mqtt" in _REGISTRY
