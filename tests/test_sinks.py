from ups_tsshara_monitor.model import UpsReading
from ups_tsshara_monitor.sinks.base import Sink, build_sinks, register_sink


def test_registry_constroi_sinks_por_nome():
    recebidos = []

    @register_sink("fake")
    class FakeSink:
        def __init__(self, config):
            self.config = config

        def start(self):
            recebidos.append("start")

        def publish(self, reading):
            recebidos.append(reading.get("input_voltage"))

        def close(self):
            recebidos.append("close")

    sinks = build_sinks(["fake"], config=object())
    assert len(sinks) == 1
    assert isinstance(sinks[0], Sink)  # respeita o Protocol em runtime

    s = sinks[0]
    s.start()
    s.publish(UpsReading(values={"input_voltage": 221.5}, status={}, online=True, timestamp="t"))
    s.close()
    assert recebidos == ["start", 221.5, "close"]


def test_sink_desconhecido_falha_claro():
    import pytest

    with pytest.raises(ValueError, match="desconhecido"):
        build_sinks(["prometheus_que_nao_existe"], config=object())
