import time
import numpy as np
from scipy import signal,fft
x=np.ones(32768,np.complex64);h=signal.firwin(33,1300000,fs=4000000).astype(np.float32)
n=fft.next_fast_len(len(x)+64);hf=fft.fft(h,n)
for name,fn in [('lfilter FIR',lambda:signal.lfilter(h,np.array([1],np.float32),x)),('lfilter denominator2',lambda:signal.lfilter(h,np.array([1,0],np.float32),x)),('upfirdn',lambda:signal.upfirdn(h,x)),('fft cached',lambda:fft.ifft(fft.fft(x,n)*hf))]:
    t=time.perf_counter()
    for i in range(200):fn()
    print(name,1000*(time.perf_counter()-t)/200)
