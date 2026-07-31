"""Testes da decodificação de status e integridade do mapa de registradores."""

from ups_tsshara_monitor import registers


def test_decode_status_todos_desligados():
    resultado = registers.decode_status(0x0000)
    assert resultado == {nome: False for nome in registers.STATUS_BITS.values()}


def test_decode_status_utility_fail_e_battery_low():
    # bit 0 (utility_fail) + bit 1 (battery_low) ligados
    resultado = registers.decode_status(0b0000_0011)
    assert resultado["utility_fail"] is True
    assert resultado["battery_low"] is True
    assert resultado["bypass_active"] is False


def test_decode_status_cobre_todos_os_bits():
    # word com todos os 8 bits mapeados ligados
    resultado = registers.decode_status(0xFF)
    assert all(resultado.values())
    assert set(resultado) == set(registers.STATUS_BITS.values())


def test_mqtt_sensors_nao_tem_field_duplicado():
    fields = [s[0] for s in registers.MQTT_SENSORS]
    assert len(fields) == len(set(fields)), "há field repetido em MQTT_SENSORS"


def test_reg_map_offsets_dentro_do_bloco():
    # Todo offset declarado precisa caber dentro do count do bloco.
    for base_reg, count, secao, campos in registers.REG_MAP:
        for offset, nome, divisor, unidade in campos:
            assert offset < count, (
                f"{secao}/{nome}: offset {offset} >= count {count}"
            )
            assert divisor != 0, f"{secao}/{nome}: divisor não pode ser zero"
