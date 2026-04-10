import time
import json
import logging
import paho.mqtt.client as mqtt

from . import config
from . import registers


_LOGGER = logging.getLogger(__name__)


def mqtt_loop(shared_state: dict, state_lock):
    client = mqtt.Client(client_id=config.SERVER_NAME)
    if config.MQTT_USER:
        client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info(f"[MQTT] Conectado ao broker {config.MQTT_HOST}:{config.MQTT_PORT}")
            # Auto discovery usando o Tópico Inteligente
            for field, name, unit, dev_class, icon in registers.MQTT_SENSORS:
                cfg = {
                    "name": f"UPS {name}",
                    "unique_id": f"{config.SERVER_NAME}_{field}",
                    "state_topic": f"{config.MQTT_TOPIC}/{field}/state",
                    "unit_of_measurement": unit,
                    "icon": icon,
                    "device": {
                        "identifiers": [config.SERVER_NAME],
                        "name": f"{config.SERVER_NAME} - Tsshara SYAL IN",
                        "manufacturer": "Tsshara",
                    },
                }
                if dev_class: cfg["device_class"] = dev_class
                c.publish(f"{config.MQTT_TOPIC}/{field}/config", json.dumps(cfg), retain=True)

            # Status textual
            status_cfg = {
                "name": "UPS Status", "unique_id": f"{config.SERVER_NAME}_status",
                "state_topic": f"{config.MQTT_TOPIC}/status/state",
                "icon": "mdi:power-plug", "device": {"identifiers": [config.SERVER_NAME]},
            }
            c.publish(f"{config.MQTT_TOPIC}/status/config", json.dumps(status_cfg), retain=True)
        else:
            _LOGGER.error(f"[MQTT] Falha na conexão: rc={rc}")

    client.on_connect = on_connect
    
    # Se o host for None, a thread MQTT dorme (útil para debug local só na serial)
    if not config.MQTT_HOST:
        _LOGGER.warning("MQTT_HOST não definido. Modo apenas leitura.")
        return
        
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, 60)
    client.loop_start()

    while True:
        time.sleep(config.POLL_SECS)
        with state_lock:
            d = dict(shared_state)
        
        if not d: continue

        for field, _, _, _, _ in registers.MQTT_SENSORS:
            if field in d:
                client.publish(f"{config.MQTT_TOPIC}/{field}/state", str(d[field]), retain=True)
        
        status = "OB LB" if d.get("utility_fail") and d.get("battery_low") else "On Battery" if d.get("utility_fail") else "Online"
        client.publish(f"{config.MQTT_TOPIC}/status/state", status, retain=True)