"""Start TS Shara UPS SYAL IN Monitor."""

import argparse
import logging
import signal

from . import config
from .poller import poll_loop
from .sinks.base import build_sinks

VERMELHO = "\033[31m"
VERDE = "\033[32m"
AZUL = "\033[34m"
RESET = "\033[0m"


logging.basicConfig(
    level=logging.INFO,
    format=f"{VERDE}%(asctime)s{RESET} | {VERMELHO}%(levelname)s{RESET} | {AZUL}%(filename)s:%(lineno)d{RESET} | %(message)s",  # noqa: E501
)
_LOGGER = logging.getLogger(__name__)


def _install_sigterm():
    # docker stop envia SIGTERM; transformamos em KeyboardInterrupt para
    # cair no finally e fechar os sinks (ex.: publicar "offline" no MQTT).
    def _handler(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handler)


def main():
    """Start TS Shara Monitor."""

    # parser de argumentos
    parser = argparse.ArgumentParser(description="Tsshara UPS SYAL IN monitor")
    parser.add_argument("--debug", action="store_true", help="Log verboso")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    _install_sigterm()

    # Monta e inicia as saídas escolhidas em SINKS (ex.: "mqtt" ou "mqtt,websocket")
    sinks = build_sinks(config.SINKS, config)
    for s in sinks:
        s.start()
    _LOGGER.info("Sinks ativos: %s", ", ".join(config.SINKS) or "(nenhum)")

    # Cria uma função dentro da função. Esse função é usada como callback para o pooler publicar
    #  os dados nos sinks
    def on_reading(reading):
        # Uma falha num sink não pode derrubar os outros nem o poller.
        for s in sinks:
            try:
                s.publish(reading)
            except Exception:
                _LOGGER.exception("Sink %s falhou ao publicar", type(s).__name__)

    _LOGGER.info("TS Shara UPS SYAL IN Monitor Iniciado com Sucesso")
    try:
        poll_loop(on_reading)
    except KeyboardInterrupt:
        _LOGGER.info("Encerrando...")
    finally:
        for s in sinks:
            try:
                s.close()
            except Exception:
                _LOGGER.exception("Erro ao fechar sink %s", type(s).__name__)


if __name__ == "__main__":
    """Start TS Shara Monitor."""
    main()
