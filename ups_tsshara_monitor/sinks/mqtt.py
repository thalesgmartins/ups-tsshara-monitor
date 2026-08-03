"""Sink MQTT — publica discovery do Home Assistant, estados e status.

É o antigo mqtt_loop reorganizado no contrato Sink:
  start()   → conecta, registra LWT e publica o discovery (no on_connect)
  publish() → publica o estado de cada sensor + o status textual
  close()   → marca offline e encerra a conexão de forma limpa
"""

import json
import logging

import paho.mqtt.client as mqtt

from .. import registers
from ..model import UpsReading
from .base import register_sink

_LOGGER = logging.getLogger(__name__)


@register_sink("mqtt")
class MqttSink:
    def __init__(self, config):
        self._cfg = config
        self._client = None
        self._avail_topic = f"{config.MQTT_TOPIC}/availability"

    # -- ciclo de vida --------------------------------------------------
    def start(self) -> None:
        if not self._cfg.MQTT_HOST:
            _LOGGER.warning("MQTT_HOST não definido. Sink MQTT inativo (modo só leitura).")
            return

        client = mqtt.Client(client_id=self._cfg.SERVER_NAME)
        # LWT: se o processo cair, o broker avisa o HA que estamos offline.
        client.will_set(self._avail_topic, "offline", qos=1, retain=True)
        if self._cfg.MQTT_USER:
            client.username_pw_set(self._cfg.MQTT_USER, self._cfg.MQTT_PASS)
        client.on_connect = self._on_connect

        client.connect_async(self._cfg.MQTT_HOST, self._cfg.MQTT_PORT, 60)
        client.loop_start()
        self._client = client

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.publish(self._avail_topic, "offline", retain=True)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001 — encerramento best-effort
            _LOGGER.debug("Falha ao encerrar cliente MQTT", exc_info=True)

    # -- publicação -----------------------------------------------------
    def publish(self, reading: UpsReading) -> None:
        if self._client is None:
            return
        base = self._cfg.MQTT_TOPIC
        for field, *_ in registers.MQTT_SENSORS:
            if field in reading.values:
                self._client.publish(
                    f"{base}/{field}/state", str(reading.values[field]), retain=True
                )
        self._client.publish(f"{base}/status/state", self._status_text(reading), retain=True)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _status_text(reading: UpsReading) -> str:
        on_battery = reading.status.get("utility_fail", False)
        bat_pct = reading.values.get("battery_charge", 0)
        if on_battery and reading.status.get("battery_low"):
            return "Low Battery"  # falta de rede + bateria baixa
        if on_battery:
            return "On Battery"  # falta de rede
        if bat_pct < 100:
            return "Charging"  # rede OK, bateria ainda carregando
        return "Online"  # rede OK e bateria cheia

    def _on_connect(self, c, userdata, flags, rc):
        if rc != 0:
            _LOGGER.error(f"[MQTT] Falha na conexão: rc={rc}")
            return

        _LOGGER.info(f"[MQTT] Conectado ao broker {self._cfg.MQTT_HOST}:{self._cfg.MQTT_PORT}")
        c.publish(self._avail_topic, "online", retain=True)

        base = self._cfg.MQTT_TOPIC
        device = {
            "identifiers": [f"ups_monitor_{self._cfg.SERVER_NAME}"],
            "name": f"Nobreak {self._cfg.SERVER_NAME}",
            "manufacturer": "Tsshara",
            "model": "SYAL IN",
        }
        for field, name, unit, dev_class, icon in registers.MQTT_SENSORS:
            cfg = {
                "name": f"UPS {name}",
                "unique_id": f"{self._cfg.SERVER_NAME}_{field}",
                "state_topic": f"{base}/{field}/state",
                "availability_topic": self._avail_topic,
                "expire_after": 120,
                "unit_of_measurement": unit,
                "icon": icon,
                "device": device,
            }
            if dev_class:
                cfg["device_class"] = dev_class
            c.publish(f"{base}/{field}/config", json.dumps(cfg), retain=True)

        status_cfg = {
            "name": "UPS Status",
            "unique_id": f"{self._cfg.SERVER_NAME}_status",
            "state_topic": f"{base}/status/state",
            "availability_topic": self._avail_topic,
            "expire_after": 120,
            "icon": "mdi:power-plug",
            "device": {"identifiers": [f"ups_monitor_{self._cfg.SERVER_NAME}"]},
        }
        c.publish(f"{base}/status/config", json.dumps(status_cfg), retain=True)
