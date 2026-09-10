import time
import numpy as np
from sdr_debug.protocols.zigbee.plugin import ZigbeePlugin
p=ZigbeePlugin();p.configure(4000000,2425e6,2425e6,{})
x=(np.random.default_rng(1).normal(size=32768)+1j*np.random.default_rng(2).normal(size=32768)).astype(np.complex64)
start=time.perf_counter()
for i in range(50):p.process_iq(x,100+i*len(x)/4e6)
print('ms/block',1000*(time.perf_counter()-start)/50)
