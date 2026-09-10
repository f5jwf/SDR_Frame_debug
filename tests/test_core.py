import json
import struct
import time
from dataclasses import replace
import numpy as np
import pytest
from scipy.signal import resample_poly
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from sdr_debug.protocols.zigbee.phy import modulate,with_fcs,crc16,ZigbeePHY,FS
from sdr_debug.protocols.zigbee.decoder import decode,secure_payload
from sdr_debug.protocols.zigbee.plugin import ZigbeePlugin
from sdr_debug.protocols.base import Frame
from sdr_debug.sdr.backends import Settings
from sdr_debug.capture.iq import Recorder,Replay
from sdr_debug.export.packets import export_frames
from sdr_debug.dsp.engine import Engine

MAC=bytes.fromhex('418801341200007856')
NWK=bytes.fromhex('0800000078561e01')
APS=bytes.fromhex('0001060004010101')
ZCL=bytes.fromhex('010101')
RAW=with_fcs(MAC+NWK+APS+ZCL)


def test_crc_known_check_value():
    assert crc16(b'123456789')==0x2189
    assert crc16(with_fcs(b'123456789'))==0


@pytest.mark.parametrize('rate',[4000000,8000000])
@pytest.mark.parametrize('cfo',[-100000,0,100000])
def test_phy_noise_phase_cfo_and_split(rate,cfo):
    rng=np.random.default_rng(42)
    iq=modulate(RAW)
    if rate==8000000:iq=resample_poly(iq,2,1)
    iq=np.concatenate((np.zeros(731),iq,np.zeros(2000)))
    iq=iq*np.exp(1j*(1.7+2*np.pi*cfo*np.arange(len(iq))/rate))
    iq+=.03*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
    p=ZigbeePlugin();p.configure(rate,2425e6,2425e6,{})
    frames=[]
    for i in range(0,len(iq),997):frames.extend(p.process_iq(iq[i:i+997],100+i/rate))
    assert len(frames)==1
    assert frames[0].raw==RAW and frames[0].crc_ok
    assert abs(frames[0].timestamp-(100+731/rate))<3e-6


def test_phy_two_packets_and_bad_crc():
    bad=RAW[:-1]+bytes([RAW[-1]^1])
    iq=np.concatenate((np.zeros(10),modulate(RAW),np.zeros(500),modulate(bad),np.zeros(1000)))
    p=ZigbeePlugin();p.configure(FS,2425e6,2425e6,{})
    frames=p.process_iq(iq,100)
    assert [f.crc_ok for f in frames]==[True,False]


def test_phy_maximum_length():
    raw=with_fcs(bytes(range(125)));iq=np.concatenate((np.zeros(77),modulate(raw),np.zeros(1000)))
    p=ZigbeePHY();frames=[]
    for i in range(0,len(iq),613):frames.extend(p.feed(iq[i:i+613],100+i/FS))
    assert [f[1] for f in frames]==[raw]
    assert len(p.buffer)<=18000


def test_nco_channel_offset():
    rate=8000000; offset=1e6
    iq=resample_poly(modulate(RAW),2,1);iq=np.concatenate((np.zeros(79),iq,np.zeros(2000)))
    iq*=np.exp(2j*np.pi*offset*np.arange(len(iq))/rate)
    p=ZigbeePlugin();p.configure(rate,2424e6,2425e6,{})
    frames=[]
    for i in range(0,len(iq),1024):frames.extend(p.process_iq(iq[i:i+1024],100+i/rate))
    assert [f.raw for f in frames]==[RAW]


def test_decoder_layers():
    tree=decode(RAW)
    assert tree['MAC']['source']=='5678'
    assert tree['MAC']['pan']=='0x1234'
    assert tree['NWK']['destination']=='0000'
    assert tree['APS']['cluster']=='0x0006'
    assert tree['ZCL']['command_name']=='On'


def test_truncated_frames_do_not_crash():
    for i in range(len(RAW)):assert isinstance(decode(RAW[:i]),dict)
    rng=np.random.default_rng(8)
    for n in range(128):assert isinstance(decode(rng.bytes(n)),dict)


def encrypted_network(key):
    header=bytes.fromhex('0802000078561e01')
    auxiliary=bytes.fromhex('2801000000080706050403020100')
    aad=header+bytes([0x2d])+auxiliary[1:]
    nonce=auxiliary[5:13]+auxiliary[1:5]+bytes([0x2d])
    encrypted=AESCCM(key,tag_length=4).encrypt(nonce,APS+ZCL,aad)
    return with_fcs(MAC+header+auxiliary+encrypted)


def test_network_decryption_and_wrong_key():
    key=bytes(range(16));raw=encrypted_network(key)
    assert 'APS' not in decode(raw)
    assert decode(raw,key)['ZCL']['command_name']=='On'
    wrong=decode(raw,bytes(16))
    assert 'APS' not in wrong and 'Échec' in wrong['NWK']['security_details']['status']
    assert key.hex() not in json.dumps(decode(raw,key))


def test_link_key():
    key=bytes(range(16));head=bytes([APS[0]|32])+APS[1:]
    aux=bytes.fromhex('20010000000807060504030201')
    aad=head+bytes([0x25])+aux[1:];nonce=aux[5:13]+aux[1:5]+b'\x25'
    cipher=AESCCM(key,tag_length=4).encrypt(nonce,ZCL,aad)
    raw=with_fcs(MAC+NWK+head+aux+cipher)
    assert decode(raw,link_key=key)['ZCL']['command_name']=='On'


def test_iq_roundtrip_and_exports(tmp_path):
    settings=Settings(backend='Rejeu SigMF');path=tmp_path/'test.sigmf-meta'
    iq=np.concatenate((np.zeros(79),modulate(RAW),np.zeros(1200)))
    rec=Recorder(path,settings);rec.write(iq,100);rec.close()
    settings.replay=str(path);replay=Replay(settings);out,ts=replay.read();replay.close()
    np.testing.assert_array_equal(out,iq.astype('<c8'));assert ts==100
    p=ZigbeePlugin();p.configure(FS,2425e6,2425e6,{})
    frames=p.process_iq(out,ts);assert [f.raw for f in frames]==[RAW]
    for ext in ['json','csv','pcap']:export_frames(tmp_path/f'frames.{ext}',frames,settings.public())
    data=(tmp_path/'frames.pcap').read_bytes();assert struct.unpack('<I',data[20:24])[0]==195
    assert data[40:]==RAW
    with pytest.raises(FileExistsError):Recorder(path,settings)


def test_engine_demo_stop_restart():
    engine=Engine();engine.start(Settings(backend='Démonstration'))
    deadline=time.monotonic()+2
    while engine.counts['ok']<2 and time.monotonic()<deadline:time.sleep(.02)
    engine.reconfigure(Settings(backend='Démonstration',gain=25))
    time.sleep(.15);engine.stop()
    for thread in engine.threads:thread.join(3)
    assert not any(t.is_alive() for t in engine.threads)
    assert engine.counts['ok']>=2
    assert engine.counts['restarts']==1


def test_out_of_band_decode_disabled():
    p=ZigbeePlugin();p.configure(4000000,2410e6,2425e6,{})
    assert not p.enabled

@pytest.mark.parametrize('rate',[2400000,2560000])
def test_rtl_resampling_odd_blocks(rate):
    from math import gcd
    divisor=gcd(rate,FS)
    iq=resample_poly(modulate(RAW),rate//divisor,FS//divisor)
    iq=np.concatenate((np.zeros(171),iq,np.zeros(2000)))
    p=ZigbeePlugin();p.configure(rate,2425e6,2425e6,{})
    frames=[]
    for i in range(0,len(iq),743):frames.extend(p.process_iq(iq[i:i+743],100+i/rate))
    assert [f.raw for f in frames]==[RAW]


def test_stream_resampler_matches_causal_reference():
    from sdr_debug.dsp.resample import Resampler
    from scipy.signal import upfirdn
    rng=np.random.default_rng(4);data=rng.normal(size=10000).astype(np.complex64)
    r=Resampler(2400000,4000000);out=[]
    for i in range(0,len(data),743):out.append(r.process(data[i:i+743]))
    output=np.concatenate(out);reference=upfirdn(r.taps,data,up=r.up,down=r.down)
    np.testing.assert_allclose(output,reference[:len(output)],atol=1e-6)


def test_pluto_one_hertz_rounding():
    p=ZigbeePlugin();p.configure(3999999,2425e6,2425e6,{})
    assert p.enabled and p.resampler is None
    iq=np.concatenate((np.zeros(73),modulate(RAW),np.zeros(1000)))
    assert [f.raw for f in p.process_iq(iq,100)]==[RAW]


def test_external_plugin_without_sdr_changes(monkeypatch):
    from sdr_debug.protocols import registry
    class Diagnostic:
        id='test';name='Test';channels={1:2425e6};bandwidth=1;min_sample_rate=1
        def configure(self,*args):self.enabled=True
        def process_iq(self,iq,ts):return [Frame(ts,1,2425e6,b'test',True,-20,{},'Test plugin')]
        def decode(self,frame):return {}
        def format_summary(self,frame):return 'Test plugin'
        def get_filters(self):return ['channel']
    class Entry:
        name='test'
        def load(self):return Diagnostic
    monkeypatch.setattr(registry,'entry_points',lambda **kwargs:[Entry()])
    assert registry.available()['test'] is Diagnostic
    e=Engine();e.start(Settings(backend='Démonstration',protocol='test',channel=1));time.sleep(.1);e.stop()
    for t in e.threads:t.join(2)
    assert e.counts['ok']>0
