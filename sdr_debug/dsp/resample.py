"""Causal rational resampling with preserved phase across arbitrary blocks."""
from fractions import Fraction
import numpy as np
from scipy.signal import firwin,upfirdn


class Resampler:
    def __init__(self, input_rate, output_rate):
        ratio=Fraction(int(output_rate),int(input_rate)).limit_denominator(1000);self.up=ratio.numerator;self.down=ratio.denominator
        if self.up==self.down: raise ValueError("Identity resampling is unnecessary")
        maximum=max(self.up,self.down)
        self.taps=(firwin(20*maximum+1,1/maximum)*self.up).astype(np.float32)
        self.delay=(len(self.taps)-1)/2/(input_rate*self.up)
        self.tail=np.empty(0,np.complex64);self.origin=0;self.total=0;self.next_output=0
    def process(self,block):
        data=np.concatenate((self.tail,block));self.total+=len(block)
        output=upfirdn(self.taps,data,up=self.up,down=self.down)
        origin_output=self.origin*self.up//self.down
        stop=(self.total*self.up+self.down-1)//self.down
        result=output[self.next_output-origin_output:stop-origin_output]
        self.next_output=stop
        retain=(len(self.taps)+self.up-1)//self.up+self.down
        new_origin=max(0,((self.total-retain)//self.down)*self.down)
        self.tail=data[new_origin-self.origin:];self.origin=new_origin
        return result
