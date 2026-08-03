import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from ups_tsshara_monitor.model import UpsReading
from ups_tsshara_monitor.sinks.base import register_sink

_LOGGER = logging.getLogger(__name__)


@register_sink("http")
class HttpSink:
    def __init__(self, config):
        # Pega a porta do .env, com fallback para 8080
        self.port = getattr(config, "HTTP_PORT", 8080)
        self.ultima_leitura: UpsReading | None = None
        self.server = None
        self.thread = None

    def start(self) -> None:
        sink_instance = self

        # Criamos o handler aqui dentro para ele ter acesso à variável `sink_instance`
        class JsonRequestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/status":
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()

                    if sink_instance.ultima_leitura:
                        # Monta o payload baseado no seu dataclass
                        payload = {
                            "online": sink_instance.ultima_leitura.online,
                            "timestamp": sink_instance.ultima_leitura.timestamp,
                            "values": sink_instance.ultima_leitura.values,
                            "status": sink_instance.ultima_leitura.status,
                        }
                        self.wfile.write(json.dumps(payload).encode("utf-8"))
                    else:
                        # Caso alguém dê o curl antes do nobreak responder a 1ª vez
                        self.wfile.write(b'{"error": "Aguardando primeira leitura"}')
                else:
                    # Se baterem em qualquer rota diferente de /status
                    self.send_response(404)
                    self.end_headers()

            # Sobrescrevemos esse método para o servidor não poluir os logs do seu terminal
            # toda vez que alguém fizer um curl
            def log_message(self, format, *args):
                pass

        self.server = HTTPServer(("0.0.0.0", self.port), JsonRequestHandler)

        # Cria a thread em modo daemon (morre automaticamente se o programa principal fechar)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        _LOGGER.info(f"HTTP Sink rodando em background na porta {self.port} (rota: /status)")

    def publish(self, reading: UpsReading) -> None:
        # Tudo que o loop Modbus faz é atualizar essa variável. Muito rápido e não bloqueia nada!
        self.ultima_leitura = reading

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2.0)
        _LOGGER.info("HTTP Sink encerrado.")
