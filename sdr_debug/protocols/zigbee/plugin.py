import numpy as np
from scipy import signal
from ..base import Frame
from .phy import ZigbeePHY, crc16, FS
from .decoder import decode
from ...dsp.resample import Resampler
from ...dsp.fir import StreamingFIR
from ...sdr.rates import SAMPLE_RATES


class ZigbeePlugin:
    id='zigbee'; name='Zigbee / IEEE 802.15.4'
    channels={c:(2405+5*(c-11))*1e6 for c in range(11,27)}
    bandwidth=2_000_000; min_sample_rate=2_400_000

    def configure(self, sample_rate, center_frequency, channel_frequency, options=None):
        self.actual_rate=float(sample_rate)
        nominal=min(SAMPLE_RATES,key=lambda r:abs(r-sample_rate))
        self.rate=nominal if abs(nominal-sample_rate)<=4 else int(sample_rate)
        self.center=center_frequency; self.frequency=channel_frequency
        self.oscillator=None
        self.step=2*np.pi*(channel_frequency-center_frequency)/self.actual_rate
        self.options=options or {}; self.phase=0.; self.decimation_phase=0; self.phy=ZigbeePHY()
        self.channel=min(self.channels,key=lambda c:abs(self.channels[c]-channel_frequency))
        self.filter_rate=FS if self.rate>8_000_000 else self.rate
        self.taps=signal.firwin(33,min(1_300_000,self.filter_rate*.45),fs=self.filter_rate).astype(np.float32)
        self.resampler=Resampler(self.rate,FS) if self.rate in SAMPLE_RATES and self.rate not in (4_000_000,8_000_000) else None
        self.fir=StreamingFIR(self.taps,2 if self.rate==8_000_000 else 1)
        self.enabled=self.rate in SAMPLE_RATES and abs(channel_frequency-center_frequency)+self.bandwidth/2 <= min(self.rate,self.options.get("rf_bandwidth") or self.rate)/2

    def reset_stream(self):
        self.phase=0.
        self.fir.history.fill(0); self.fir.total=0
        if self.resampler is not None:
            self.resampler.tail=np.empty(0,np.complex64)
            self.resampler.origin=0; self.resampler.total=0; self.resampler.next_output=0
        self.phy.buffer=np.empty(0,np.complex64); self.phy.cursor=0

    def process_iq(self, iq_block, timestamp):
        if not self.enabled: return []
        if self.step:
            if self.oscillator is None or len(self.oscillator)!=len(iq_block):
                self.oscillator=np.exp(-1j*self.step*np.arange(len(iq_block))).astype(np.complex64)
            rotation=np.complex64(np.exp(-1j*self.phase))
            iq=np.asarray(iq_block,dtype=np.complex64)*self.oscillator
            iq*=rotation
            self.phase=(self.phase+self.step*len(iq_block))%(2*np.pi)
        else:iq=np.asarray(iq_block,dtype=np.complex64)
        if self.rate>8_000_000:
            iq=self.resampler.process(iq)
            timestamp-=self.resampler.delay
        iq,offset=self.fir.process(iq)
        timestamp+=offset/self.filter_rate
        if self.resampler is not None and self.rate<4_000_000:
            iq=self.resampler.process(iq)
            timestamp-=self.resampler.delay
        frames=[]
        for ts, raw, power, cfo in self.phy.feed(iq,timestamp-16/self.filter_rate):
            frame=Frame(ts,self.channel,self.frequency,raw,crc16(raw[:-2])==int.from_bytes(raw[-2:],'little'),power)
            frame.fields={'PHY':{'PHR':len(raw),'length':len(raw),'FCS':'OK' if frame.crc_ok else 'BAD','CFO_Hz':round(cfo)},**self.decode(frame)}
            frame.summary=self.format_summary(frame); frames.append(frame)
        return frames

    def decode(self, frame): return decode(frame.raw,self.options.get('network_key'),self.options.get('link_key'))
    def format_summary(self, frame):
        f=frame.fields; mac=f.get('MAC',{}); aps=f.get('APS',{}); zcl=f.get('ZCL',{})
        return f"{mac.get('type','?')} {mac.get('source','?')} → {mac.get('destination','?')} {aps.get('cluster_name','')} {zcl.get('command_name','')}".strip()
    def get_filters(self):
        return ['channel','MAC.source','MAC.destination','MAC.pan','MAC.type','APS.cluster','APS.source_endpoint','APS.destination_endpoint','ZCL.command']
