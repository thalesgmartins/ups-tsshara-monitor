import os

# Configurações do Servidor
SERVER_NAME = os.getenv("SERVER_NAME", "ups_tsshara_monitor")

# Configurações do MQTT
MQTT_HOST   = os.getenv("MQTT_HOST")
MQTT_PORT   = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER   = os.getenv("MQTT_USER")
MQTT_PASS   = os.getenv("MQTT_PASS")

# Tópicos MQTT
MQTT_PREFIX = os.getenv("MQTT_PREFIX", "homeassistant/sensor")
MQTT_TOPIC = f"{MQTT_PREFIX.rstrip('/')}/{SERVER_NAME}"

# Configurações do Serial
PORT        = os.getenv("SERIAL_PORT","/dev/ttyTSSHARA0")
BAUD        = int(os.getenv("SERIAL_BAUD", 9600))
SLAVE_ID    = int(os.getenv("SERIAL_SLAVE_ID", 1))
POLL_SECS   = int(os.getenv("SERIAL_POLL_SECS", 5))