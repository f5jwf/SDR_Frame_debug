import sys
import time
import types
import json
import numpy as np
import pytest
from sdr_debug.dsp.spectrum import Spectrum
from sdr_debug.dsp.engine import Engine
from sdr_debug.sdr.backends import Settings,Pluto
from sdr_debug.capture.iq import Recorder


def test_bin_centered_tone_level_and_gain():
    n=2048; iq=(.1*np.exp(2j*np.pi*73*np.arange(n*3)/n)).astype(np.complex64)
    levels=[]
    for scale in (1,10):
        analyzer=Spectrum(n); analyzer.feed(iq*scale)
        power,metrics=analyzer.snapshot()
        levels.append(float(power.max()))
        assert metrics['rms_dbfs']==pytest.approx(-20+20*np.log10(scale),abs=.001)
    assert levels==pytest.approx([-20,0],abs=.001)


def test_burst_at_start_not_discarded_and_arbitrary_blocks():
    iq=np.zeros(32768,np.complex64);iq[:2048]=.1
    analyzer=Spectrum(2048)
    for i in range(0,len(iq),743):analyzer.feed(iq[i:i+743])
    peak,metrics=analyzer.snapshot()
    assert peak.max()==pytest.approx(-20,abs=.001)
    assert metrics['fft_windows']==16
    analyzer.feed(iq);mean,_=analyzer.snapshot('mean')
    assert mean.max()==pytest.approx(-20-10*np.log10(16),abs=.001)


def test_dc_default_preserves_center_carrier():
    assert Settings().dc is False
    analyzer=Spectrum(2048);analyzer.feed(np.full(4096,.01,np.complex64))
    power,_=analyzer.snapshot()
    assert power[1024]==pytest.approx(-40,abs=.001)


def test_pluto_sets_manual_before_gain_and_reads_actual(monkeypatch):
    class Device:
        def __init__(self): self.mode='slow_attack';self.actual=20
        @property
        def gain_control_mode_chan0(self):return self.mode
        @gain_control_mode_chan0.setter
        def gain_control_mode_chan0(self,v):self.mode=v
        @property
        def rx_hardwaregain_chan0(self):return self.actual
        @rx_hardwaregain_chan0.setter
        def rx_hardwaregain_chan0(self,v):
            assert self.mode=='manual';self.actual=round(v)
    source=Pluto.__new__(Pluto);source.device=Device();source.settings=Settings()
    state=source.set_gain(49.7,False)
    assert state=={'gain':50.,'agc':False,'mode':'manual'}
    assert source.settings.gain==50
    assert source.set_gain(30,True)['mode']=='slow_attack'


def test_live_gain_does_not_reopen_or_restart(monkeypatch):
    from sdr_debug.dsp import engine as module
    class Source:
        def __init__(self):self.settings=Settings();self.closed=False;self.calls=[]
        def read(self):time.sleep(.01);return np.ones(8192,np.complex64)*.001,time.time()
        def set_gain(self,gain,agc):
            self.calls.append(gain);self.settings.gain=gain;return self.gain_state()
        def gain_state(self):return {'gain':self.settings.gain,'agc':False,'mode':'manual'}
        def close(self):self.closed=True
    source=Source();opened=[]
    def open_source(s):source.settings=s;opened.append(s);return source
    monkeypatch.setattr(module,'open_source',open_source)
    engine=Engine();engine.start(Settings())
    engine.set_gain(50,False)
    deadline=time.monotonic()+2
    while not source.calls and time.monotonic()<deadline:time.sleep(.01)
    engine.stop()
    for t in engine.threads:t.join(2)
    assert source.calls==[50] and len(opened)==1 and source.closed
    assert engine.counts['restarts']==0


def test_gain_capture_metadata_retains_initial_settings(tmp_path):
    settings=Settings(gain=30);path=tmp_path/'iq.sigmf-meta';r=Recorder(path,settings)
    r.write(np.ones(8,np.complex64),100)
    settings.gain=50;r.note_gain({'gain':50,'mode':'manual'});r.close()
    metadata=json.loads(path.read_text())
    assert metadata['global']['sdr_debug:settings']['gain']==30
    assert metadata['annotations'][0]['core:sample_start']==8
