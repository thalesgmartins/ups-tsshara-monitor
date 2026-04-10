"""Start TS Shara UPS SYAL IN Monitor."""

import argparse
import logging
import threading
import time

from .poller import poll_loop
from .mqtt import mqtt_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_LOGGER = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Tsshara UPS SYAL IN monitor")
    parser.add_argument("--debug",  action="store_true", help="Log verboso")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # A "memória" compartilhada entre as rotinas
    shared_state = {}
    state_lock = threading.Lock()

    # Passamos a memória para as threads
    t_poll = threading.Thread(target=poll_loop, args=(shared_state, state_lock), daemon=True, name="poll")
    t_poll.start()

    t_mqtt = threading.Thread(target=mqtt_loop, args=(shared_state, state_lock), daemon=True, name="mqtt")
    t_mqtt.start()

    _LOGGER.info("TS Shara UPS SYAL IN Monitor Iniciado com Sucesso")
    try:
        while True:
            time.sleep(1)
    except Exception as e:
        _LOGGER.info("Encerrando. Motivo: %s", e)

if __name__ == "__main__":
    main()