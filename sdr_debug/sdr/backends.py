from dataclasses import dataclass, asdict
import time
import numpy as np
from ..protocols.zigbee.phy import modulate, with_fcs


@dataclass
class Settings:
    backend: str='PlutoSDR'
    uri: str='ip:192.168.2.1'
    center: float=2425e6
    sample_rate: int=4_000_000
    rf_bandwidth: float=0
    gain: float=30
    agc: bool=False
    offset: float=0
    channel: int=15
    span: float=4e6
    replay: str=''
    protocol: str='zigbee'
    fft_size: int=2048
    window: str='hann'
    spectrum_mode: str='peak'
    average: float=0.3
    waterfall_ms: int=50
    history: int=30
    palette: str='viridis'
    floor: float=-90
    ceiling: float=0
    dc: bool=False
    capture_dir: str=""
    search: str=""
    filter_field: str=""
    filter_value: str=""
    show_bad: bool=False
    favorites_only: bool=False
    newest_first: bool=False
    workspace: str='zigbee'
    rx_frequency: float=433920000
    channel_width: float=200000
    modulation: str='auto'
    rtl433_path: str=''
    decoder_ids: str=''
    fsk_detector: str='classic'
    pro501_enabled: bool=True

    def public(self): return asdict(self)


class Demo:
    def __init__(self, settings):
        self.settings=settings; self.rng=np.random.default_rng(802154); self.counter=0; self.pos=0
        self.start=time.time(); self.wave=np.empty(0,np.complex64)
    def read(self):
        n=131072; rate=self.settings.sample_rate
        if len(self.wave)<n:
            seq=self.counter%256; self.counter+=1
            mac=bytes.fromhex('4188')+bytes([seq])+bytes.fromhex('341200007856')
            nwk=bytes.fromhex('0800000078561e')+bytes([seq])
            aps=bytes.fromhex('00010600040101')+bytes([seq])
            zcl=bytes([1,seq,seq%3])
            burst=modulate(with_fcs(mac+nwk+aps+zcl))
            if rate!=4_000_000:
                from scipy.signal import resample_poly
                from math import gcd
                divisor=gcd(int(rate),4000000)
                burst=resample_poly(burst,int(rate)//divisor,4000000//divisor)
            offset=(2425e6-self.settings.center)
            burst=burst*np.exp(2j*np.pi*(offset+18000)*np.arange(len(burst))/rate)
            self.wave=np.concatenate((self.wave, np.zeros(int(rate*.08),np.complex64),.5*burst))
        out=self.wave[:n].copy(); self.wave=self.wave[n:]
        out+=.015*(self.rng.normal(size=n)+1j*self.rng.normal(size=n))
        ts=self.start+self.pos/rate; self.pos+=n
        return out.astype(np.complex64),ts
    def close(self): pass


class Pluto:
    def __init__(self, settings):
        import adi
        tune=settings.center-settings.offset
        if not 325e6<=tune<=3.8e9: raise ValueError('Pluto standard : accord entre 325 et 3800 MHz')
        if not 521000<=settings.sample_rate<=61440000: raise ValueError('Pluto : taux entre 0,521 et 61,44 MS/s')
        if not -3<=settings.gain<=73: raise ValueError('Gain Pluto : -3 à 73 dB')
        self.device=adi.Pluto(uri=settings.uri or None)
        self.device._ctx.set_timeout(1500)
        self.device.rx_lo=int(tune); self.device.sample_rate=int(settings.sample_rate)
        self.device.rx_rf_bandwidth=int(min(settings.sample_rate, 20e6))
        self.device.rx_buffer_size=131072
        self.settings=settings
        self.set_gain(settings.gain,settings.agc)
        settings.rf_bandwidth=int(self.device.rx_rf_bandwidth)
        settings.sample_rate=int(self.device.sample_rate); settings.center=float(self.device.rx_lo)+settings.offset
        settings.gain=float(self.device.rx_hardwaregain_chan0); self.settings=settings
    def set_gain(self, gain, agc):
        if not -3<=gain<=73: raise ValueError('Gain Pluto : -3 à 73 dB')
        self.device.gain_control_mode_chan0='slow_attack' if agc else 'manual'
        if not agc: self.device.rx_hardwaregain_chan0=float(gain)
        state=self.gain_state()
        self.settings.gain=state['gain']; self.settings.agc=state['agc']
        return state
    def gain_state(self):
        mode=self.device.gain_control_mode_chan0
        return {'gain':float(self.device.rx_hardwaregain_chan0),'agc':mode!='manual','mode':mode}
    def read(self):
        iq=np.asarray(self.device.rx(),dtype=np.complex64)/2048.0
        return iq,time.time()-len(iq)/self.settings.sample_rate
    def close(self): self.device.rx_destroy_buffer()


class RTL:
    def __init__(self, settings):
        from rtlsdr import RtlSdr
        tune=settings.center-settings.offset
        if not .5e6<=tune<=1.766e9: raise ValueError('RTL-SDR : 0,5–1766 MHz. Pour Zigbee, régler l’offset du convertisseur.')
        if settings.sample_rate>2_560_000: raise ValueError('RTL-SDR : choisir un taux ≤ 2,56 MS/s .')
        self.device=RtlSdr(device_index=int(settings.uri) if settings.uri.isdigit() else 0); self.settings=settings
        try:
            self.device.center_freq=tune; self.device.sample_rate=settings.sample_rate
            self.device.gain='auto' if settings.agc else settings.gain
            settings.center=float(self.device.center_freq)+settings.offset
            settings.sample_rate=int(self.device.sample_rate)
            if not settings.agc: settings.gain=float(self.device.gain)
        except Exception: self.device.close(); raise
    def read(self):
        iq=np.asarray(self.device.read_samples(32768),dtype=np.complex64)
        return iq,time.time()-len(iq)/self.settings.sample_rate
    def close(self): self.device.close()


def discover():
    result=[]
    try:
        import iio
        result += [('PlutoSDR',uri,label) for uri,label in iio.scan_contexts().items()]
    except Exception: pass
    try:
        from rtlsdr import RtlSdr
        result += [('RTL-SDR',str(i),name) for i,name in enumerate(RtlSdr.get_device_names())]
    except Exception: pass
    return result


def open_source(settings):
    if settings.backend=='Démonstration':
        if settings.workspace!='zigbee':
            from ..protocols.ism.demo import ISMDemo
            return ISMDemo(settings)
        return Demo(settings)
    if settings.backend=='Rejeu SigMF':
        from ..capture.iq import Replay
        return Replay(settings)
    if settings.backend=='PlutoSDR': return Pluto(settings)
    if settings.backend=='RTL-SDR': return RTL(settings)
    raise ValueError('Backend inconnu')
