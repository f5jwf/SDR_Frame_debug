import cProfile,pstats,time
import numpy as np
from sdr_debug.protocols.zigbee.plugin import ZigbeePlugin
from sdr_debug.dsp.spectrum import Spectrum
p=ZigbeePlugin();p.configure(4000000,2406e6,2405e6,{})
a=Spectrum(2048)
rng=np.random.default_rng(7);iq=(rng.normal(size=32768)+1j*rng.normal(size=32768)).astype(np.complex64)*.01
profile=cProfile.Profile();profile.enable()
for i in range(200):
    p.process_iq(iq,100+i*len(iq)/4e6);a.feed(iq)
    if i%6==0:a.snapshot()
profile.disable();pstats.Stats(profile).strip_dirs().sort_stats('cumtime').print_stats(20)
