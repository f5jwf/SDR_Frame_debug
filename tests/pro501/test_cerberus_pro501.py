from pathlib import Path
import pytest
from sdr_debug.protocols.ism.cerberus_pro501 import (
    PRO501_FRAME_BITS, PRO501_SENSOR_PROFILES, discriminate_pro501_bits, compare_frames, decode_pro501, deglitch_edges, match_sensor_profile, parse_hex_records,
)


FRAME_A = '0000000000000000000000000000000000010110001000000000000000001000'
FRAME_B = '0000000000000000000000000000000001001101110000000000000000001011'
FRAME_C = '0000000000000000000000000000000001000010110000000000000000001011'


def burst(bits, short, long, repeats=6, drop=None):
    edges = [(0, 4000)]
    for index in range(repeats):
        current = bits if index != drop else bits[:21] + bits[22:]
        for bit in current:
            high = round(1200 * (short if bit == '1' else long))
            edges.extend(((1, high), (0, 1200-high)))
        # A non-symbol mark keeps the end-of-burst silence distinct from the
        # final symbol's LOW time in this edge-level fixture.
        edges.extend(((1, 60), (0, 12000)))
    return edges


def test_parse_and_deglitch():
    assert parse_hex_records('010297000002') == [(1, 663), (0, 2)]
    assert deglitch_edges([(1, 500), (0, 10), (1, 200)]) == [(1, 710)]
    with pytest.raises(ValueError): parse_hex_records('0102')
    with pytest.raises(ValueError): parse_hex_records('020001')


@pytest.mark.parametrize('bits,short,long', [(FRAME_A, .22, .55), (FRAME_B, .37, .70), (FRAME_C, .37, .70)])
def test_adaptive_consensus_for_each_sensor(bits, short, long):
    result = decode_pro501(burst(bits, short, long))
    assert result and result.valid and result.raw_bits == bits
    assert result.repeats >= 3 and result.frame_confidence >= .85
    assert result.event == 'ALARM' and result.battery == 'UNKNOWN'


def test_low_battery_duty_cycle_and_missing_symbol_remain_decodable():
    result = decode_pro501(burst(FRAME_A, .07, .40, drop=2))
    assert result and result.valid and result.repeats >= 3
    assert result.ratio_long - result.ratio_short >= .12


def test_templates_are_distinct_without_assuming_field_positions():
    assert compare_frames(FRAME_A, FRAME_B)
    assert compare_frames(FRAME_B, FRAME_C)


def test_learned_profile_requires_unambiguous_radio_signature():
    profile, distance, margin, distances = match_sensor_profile(PRO501_SENSOR_PROFILES['B'])
    assert profile == 'B' and distance == 0 and margin >= 1
    assert distances['B'] == 0


def test_discrimination_exposes_the_full_raw_bitstream_before_consensus():
    bits = discriminate_pro501_bits(burst(FRAME_B, .37, .70, repeats=4))
    assert bits is not None and FRAME_B in bits and len(bits) >= 4 * PRO501_FRAME_BITS
