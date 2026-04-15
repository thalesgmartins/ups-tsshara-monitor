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

            # 2. Publicar que estamos Online assim que conectar
            c.publish(avail_topic, "online", retain=True)

            # Auto discovery usando o Tópico Inteligente
            for field, name, unit, dev_class, icon in registers.MQTT_SENSORS:
                cfg = {
                    "name": f"UPS {name}",
                    "unique_id": f"{config.SERVER_NAME}_{field}",
                    "state_topic": f"{config.MQTT_TOPIC}/{field}/state",
                    "availability_topic": avail_topic, # Adicionado
                    "expire_after": 120,               # 2 minutos
                    "unit_of_measurement": unit,
                    "icon": icon,
                    "device": {
                        "identifiers": [f"ups_monitor_{config.SERVER_NAME}"],
                        "name": f"Nobreak {config.SERVER_NAME}",
                        "manufacturer": "Tsshara",
                        "model": "SYAL IN",
                    },
                }
                if dev_class: cfg["device_class"] = dev_class
                c.publish(f"{config.MQTT_TOPIC}/{field}/config", json.dumps(cfg), retain=True)

            # Status textual
            status_cfg = {
                "name": "UPS Status", "unique_id": f"{config.SERVER_NAME}_status",
                "state_topic": f"{config.MQTT_TOPIC}/status/state",
                "availability_topic": avail_topic, # Adicionado
                "expire_after": 120,               # 2 minutos
                "icon": "mdi:power-plug", 
                "device": {"identifiers": [f"ups_monitor_{config.SERVER_NAME}"]},
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
        


        #
        # Aqui é definido como vai se comportar a parte de status do sensor
        #
        is_on_battery = d.get("utility_fail", False)
        bat_pct = d.get("battery_charge", 0)
        
        # Aplica as regras de negócio
        if is_on_battery and d.get("battery_low"):
            status = "Low Battery"  # Falta de rede + Bateria Baixa
        elif is_on_battery:
            status = "On Battery"  # Falta de rede
        elif not is_on_battery and bat_pct < 100:
            status = "Charging"    # Rede OK, mas bateria ainda não chegou em 100%
        else:
            status = "Online"      # Rede OK e bateria totalmente carregada

        client.publish(f"{config.MQTT_TOPIC}/status/state", status, retain=True)