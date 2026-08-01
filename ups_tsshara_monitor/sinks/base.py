"""Interface de saída (Sink) + registry de plugins.

Todo destino de dados (MQTT, WebSocket, NUT, Prometheus...) implementa esta
interface. O núcleo produz UpsReading; os sinks consomem. Nenhum sink conhece
o outro, e o núcleo não conhece sink nenhum em concreto — só o contrato.
"""

from typing import Protocol, runtime_checkable

from ..model import UpsReading


@runtime_checkable
class Sink(Protocol):
    def start(self) -> None: ...
    def publish(self, reading: UpsReading) -> None: ...
    def close(self) -> None: ...


_REGISTRY: dict[str, type] = {}


def register_sink(name: str):
    def deco(cls):
        _REGISTRY[name] = cls
        return cls

    return deco


def build_sinks(names: list[str], config) -> list[Sink]:
    faltando = [n for n in names if n not in _REGISTRY]
    if faltando:
        raise ValueError(f"sink(s) desconhecido(s): {faltando}. Disponíveis: {list(_REGISTRY)}")
    return [_REGISTRY[n](config) for n in names]
