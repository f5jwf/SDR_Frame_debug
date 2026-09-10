"""Synthetic, receive-only fixtures for two documented device protocols.

Wire formats: rtl_433 25.12 src/devices/nexus.c and lacrosse_tx35.c.
These samples are generated locally, never transmitted.
"""
import time
from math import gcd
import numpy as np
from scipy.signal import resample_poly


def nexus_wave():
    # ID 0x42, battery OK, channel 1, 25.1 C and 52 percent humidity.
    bits=f'{int("4280fbf34",16):036b}'
    parts=[np.zeros(10000,np.float32)]
    for _ in range(12):
        for bit in bits:parts.extend((np.ones(500,np.float32),np.zeros(2000 if bit=='1' else 1000,np.float32)))
        parts.extend((np.ones(500,np.float32),np.zeros(4000,np.float32)))
    parts.append(np.zeros(20000,np.float32))
    envelope=np.concatenate(parts)
    return (.5*envelope*np.exp(2j*np.pi*12000*np.arange(len(envelope))/1e6)).astype(np.complex64)


def lacrosse_wave():
    payload=bytes.fromhex('91065134');crc=0
    for byte in payload:
        crc^=byte
        for _ in range(8):crc=((crc<<1)^0x31 if crc&0x80 else crc<<1)&255
    bits=np.unpackbits(np.frombuffer(b'\xaa'*4+b'\x2d\xd4'+payload+bytes([crc]),dtype=np.uint8))
    frequency=np.repeat(bits.astype(np.float32)*80000-40000,55)
    burst=(.5*np.exp(2j*np.pi*np.cumsum(frequency,dtype=np.float64)/1e6)).astype(np.complex64)
    return np.concatenate((np.zeros(10000,np.complex64),burst,np.zeros(20000,np.complex64)))


class ISMDemo:
    def __init__(self,settings):
        self.settings=settings;self.pos=0;self.start=time.time();self.cursor=0
        self.rng=np.random.default_rng(433868)
        wave=nexus_wave() if settings.workspace=='ism433' else lacrosse_wave()
        rate=int(settings.sample_rate)
        if rate!=1000000:
            divisor=gcd(rate,1000000);wave=resample_poly(wave,rate//divisor,1000000//divisor)
        wave=wave*np.exp(2j*np.pi*(settings.rx_frequency-settings.center)*np.arange(len(wave))/rate)
        self.wave=np.concatenate((wave,np.zeros(int(rate*.5),np.complex64))).astype(np.complex64)
    def read(self):
        count=131072;indices=(self.cursor+np.arange(count))%len(self.wave)
        iq=self.wave[indices].copy();self.cursor=(self.cursor+count)%len(self.wave)
        iq+=.005*(self.rng.normal(size=count)+1j*self.rng.normal(size=count))
        timestamp=self.start+self.pos/self.settings.sample_rate;self.pos+=count
        return iq,timestamp
    def close(self):pass
