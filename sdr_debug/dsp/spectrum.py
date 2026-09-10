"""Continuous FFT analysis. Every complete FFT is included between refreshes."""
import numpy as np
from scipy import fft, signal


class Spectrum:
    def __init__(self, size, window='hann', average=.3):
        self.size=size
        self.window=signal.get_window(window,size).astype(np.float32)
        self.scale=float(self.window.sum())**2
        self.average=average
        self.tail=np.empty(0,np.complex64)
        self.smoothed=None
        self.reset_interval()

    def reset_interval(self):
        self.maximum=None; self.sum=None; self.windows=0
        self.energy=0.; self.samples=0; self.component_peak=0.; self.clipped=0

    def feed(self, iq):
        self.energy+=float(np.vdot(iq,iq).real)
        self.samples+=len(iq)
        component=np.maximum(abs(iq.real),abs(iq.imag))
        if len(iq): self.component_peak=max(self.component_peak,float(component.max()))
        self.clipped+=int(np.count_nonzero(component>=2047/2048))
        data=np.concatenate((self.tail,iq))
        count=len(data)//self.size
        self.tail=data[count*self.size:].copy()
        if not count:return
        transformed=fft.fft(data[:count*self.size].reshape(count,self.size)*self.window,axis=1)
        power=(transformed.real**2+transformed.imag**2)/self.scale
        maximum=power.max(axis=0); total=power.sum(axis=0)
        self.maximum=maximum if self.maximum is None else np.maximum(self.maximum,maximum)
        self.sum=total if self.sum is None else self.sum+total
        self.windows+=count

    def snapshot(self, mode='peak'):
        if not self.windows:return None
        mean=self.sum/self.windows
        self.smoothed=mean if self.smoothed is None else self.average*mean+(1-self.average)*self.smoothed
        power=self.maximum if mode=='peak' else self.smoothed
        result=10*np.log10(np.fft.fftshift(power)+1e-20)
        metrics={'rms_dbfs':10*np.log10(self.energy/max(1,self.samples)+1e-20),
                 'peak_dbfs':20*np.log10(self.component_peak+1e-20),
                 'clip_percent':100*self.clipped/max(1,self.samples),
                 'fft_windows':self.windows}
        self.reset_interval()
        return result,metrics
