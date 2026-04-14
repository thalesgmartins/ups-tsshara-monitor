"""Start TS Shara UPS SYAL IN Monitor."""

import argparse
import logging
import threading
import time

from .poller import poll_loop
from .mqtt import mqtt_loop

VERMELHO = "\033[31m"
VERDE = "\033[32m"
AZUL= "\033[34m"
RESET = "\033[0m"

logging.basicConfig(level=logging.INFO, format=f"{VERDE}%(asctime)s{RESET} | {VERMELHO}%(levelname)s{RESET} | {AZUL}%(filename)s:%(lineno)d{RESET} | %(message)s")
_LOGGER = logging.getLogger(__name__)


def main():
    # parser de argumentos
    parser = argparse.ArgumentParser(description="Tsshara UPS SYAL IN monitor")
    parser.add_argument("--debug",  action="store_true", help="Log verboso")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Cria a memória compartilhada para todas as rotinas
    shared_state = {}
    state_lock = threading.Lock()

    # Cria a inicia a thread do Polling Serial
    t_poll = threading.Thread(target=poll_loop, args=(shared_state, state_lock), daemon=True, name="poll")
    t_poll.start()

    # Cria a inicia a thread do Mqtt
    t_mqtt = threading.Thread(target=mqtt_loop, args=(shared_state, state_lock), daemon=True, name="mqtt")
    t_mqtt.start()

    _LOGGER.info("TS Shara UPS SYAL IN Monitor Iniciado com Sucesso")
    try:
        while True:
            time.sleep(1)
    except Exception as e:
        _LOGGER.info("Encerrando. Motivo: %s", e)

if __name__ == "__main__":
    """Start TS Shara Monitor."""
    main()