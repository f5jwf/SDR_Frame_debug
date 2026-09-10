"""Causal FIR using batched overlap-save; preserves phase across blocks."""
import numpy as np
from scipy import fft


class StreamingFIR:
    def __init__(self,taps,decimation=1):
        self.taps=np.asarray(taps,dtype=np.float32);self.down=decimation
        self.history=np.zeros(len(self.taps)-1,np.complex64);self.total=0
        self.size=fft.next_fast_len(max(256,4*len(self.taps)))
        self.kernel=fft.fft(self.taps,self.size)
    def process(self,block):
        first_offset=(-self.total)%self.down;self.total+=len(block)
        overlap=len(self.history);step=self.size-overlap
        data=np.concatenate((self.history,block))
        count=(len(block)+step-1)//step
        if not count:return np.empty(0,np.complex64),first_offset
        padded=np.pad(data,(0,count*step+overlap-len(data)))
        chunks=np.lib.stride_tricks.sliding_window_view(padded,self.size)[::step]
        transformed=fft.fft(chunks,axis=1);transformed*=self.kernel
        valid=fft.ifft(transformed,axis=1)[:,overlap:].ravel()[:len(block)]
        result=valid[first_offset::self.down].copy()
        if overlap:self.history=data[-overlap:].copy()
        return result,first_offset
