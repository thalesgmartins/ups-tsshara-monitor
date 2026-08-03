"""Pacote de sinks. Importar os sinks internos aqui faz o @register_sink
disparar, populando o registry antes de build_sinks ser chamado.
"""

from . import mqtt as _mqtt  # noqa: F401  (efeito colateral: registra "mqtt")
