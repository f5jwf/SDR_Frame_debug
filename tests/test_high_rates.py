from math import gcd
import numpy as np
import pytest
from scipy.signal import resample_poly
from sdr_debug.protocols.zigbee.phy import modulate,with_fcs,FS
from sdr_debug.protocols.zigbee.plugin import ZigbeePlugin
from sdr_debug.sdr.rates import SAMPLE_RATES,usable_bandwidth
from sdr_debug.sdr.backends import Settings

RAW=with_fcs(bytes.fromhex('4188013412000078560800000078561e010001060004010101010101'))


@pytest.mark.parametrize('rate',[r for r in SAMPLE_RATES if r>8_000_000])
def test_high_rate_decoder_with_offset_and_odd_blocks(rate):
    divisor=gcd(rate,FS)
    iq=resample_poly(modulate(RAW),rate//divisor,FS//divisor)
    iq=np.concatenate((np.zeros(739),iq,np.zeros(3000))).astype(np.complex64)
    iq*=np.exp(2j*np.pi*3_000_000*np.arange(len(iq))/rate)
    plugin=ZigbeePlugin();plugin.configure(rate,2422e6,2425e6,{'rf_bandwidth':min(rate,20e6)})
    frames=[]
    for i in range(0,len(iq),8171):frames.extend(plugin.process_iq(iq[i:i+8171],100+i/rate))
    assert [f.raw for f in frames]==[RAW]
    assert all(f.crc_ok for f in frames)
    assert abs(frames[0].timestamp-(100+739/rate))<3e-6


def test_rf_filter_limit_is_not_sample_rate():
    settings=Settings(sample_rate=61440000,rf_bandwidth=20000000)
    assert usable_bandwidth(settings)==20000000
    plugin=ZigbeePlugin();plugin.configure(61440000,2405e6,2425e6,{'rf_bandwidth':20000000})
    assert not plugin.enabled
    plugin.configure(61439999,2425e6,2425e6,{'rf_bandwidth':20000000})
    assert plugin.enabled and plugin.rate==61440000
