"""Compiled loops for normalized correlation and symbol decisions.

No approximate trigonometry, energy gate or relaxed detection threshold.
"""
import math
import numpy as np
from numba import njit


@njit(cache=True,nogil=True)
def correlation_scores(d,corr,length,energy):
    out=np.zeros(len(corr),np.float32)
    total=0.;squares=0.
    for j in range(length):
        v=np.float64(d[j]);total+=v;squares+=v*v
    for i in range(len(corr)):
        variance=max((squares-total*total/length)*energy,1e-12)
        c=np.float64(corr[i])
        # Below-threshold positions cannot be detected; avoid their square root.
        if c>0 and c*c>=.78*.78*variance:out[i]=c/math.sqrt(variance)
        if i+length<len(d):
            old=np.float64(d[i]);new=np.float64(d[i+length])
            total+=new-old;squares+=new*new-old*old
    return out


@njit(cache=True,nogil=True)
def decode_bytes(d,start,count,cfo,symbols):
    result=np.empty(count,np.uint8)
    for byte in range(count):
        value=0
        for half in range(2):
            pos=start+(2*byte+half)*64+4
            best=0;minimum=math.inf
            for symbol in range(16):
                error=0.
                for j in range(59):
                    delta=np.float64(symbols[symbol,j])-(np.float64(d[pos+j])-cfo)
                    error+=delta*delta
                if error<minimum:minimum=error;best=symbol
            value|=best<<(half*4)
        result[byte]=value
    return result


@njit(cache=True,nogil=True)
def phase_difference(iq):
    out=np.empty(max(0,len(iq)-1),np.float32)
    for i in range(len(out)):
        x=iq[i+1].real*iq[i].real+iq[i+1].imag*iq[i].imag
        y=iq[i+1].imag*iq[i].real-iq[i+1].real*iq[i].imag
        out[i]=math.atan2(y,x)
    return out


def warmup():
    phase_difference(np.zeros(4,np.complex64))
    correlation_scores(np.zeros(640,np.float32),np.zeros(6,np.float32),635,1.)
    decode_bytes(np.zeros(128,np.float32),0,1,0.,np.zeros((16,59),np.float32))
