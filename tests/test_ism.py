import json
import time
import numpy as np
import pytest
from sdr_debug import config
from sdr_debug.export.packets import export_frames
from sdr_debug.protocols.ism.demo import nexus_wave,lacrosse_wave
from sdr_debug.protocols.ism.plugin import ISM433Plugin,ISM868Plugin,executable,protocol_ids


@pytest.mark.parametrize('cls,wave,model,crc',[
    (ISM433Plugin,nexus_wave,'Nexus-TH',None),
    (ISM868Plugin,lacrosse_wave,'LaCrosse-TX29IT',True),
])
def test_real_rtl433_iq_decode_across_blocks(cls,wave,model,crc,tmp_path):
    if not executable():pytest.skip('Install the official rtl_433 runtime for integration tests')
    p=cls();frequency=next(iter(p.channels.values()));p.configure(1000000,frequency,frequency,{})
    iq=wave();frames=[]
    try:
        for i in range(0,len(iq),65536):
            frames.extend(p.process_iq(iq[i:i+65536],100+i/1e6));time.sleep(.02)
    finally:frames.extend(p.finish())
    matching=[f for f in frames if f.fields['rtl_433']['model']==model]
    assert matching
    frame=matching[0];fields=frame.fields['rtl_433']
    assert fields['temperature_C']==pytest.approx(25.1) and fields['humidity']==52
    assert frame.crc_ok is crc and frame.protocol==cls.id
    assert abs(frame.timestamp-100.01)<.0001
    assert p.process.poll()==0 and not any(t.is_alive() for t in p.readers+[p.writer])
    export_frames(tmp_path/'frames.json',frames)
    obj=json.loads((tmp_path/'frames.json').read_text(encoding='utf8'))
    assert obj['frames'][0]['level'] is None
    with pytest.raises(ValueError):export_frames(tmp_path/'invalid.pcap',frames)
    assert not (tmp_path/'invalid.pcap').exists()


def test_missing_decoder_preserves_spectrum_mode():
    p=ISM433Plugin();p.configure(1000000,433920000,433920000,{'rtl433_path':'missing-rtl433.exe'})
    assert not p.enabled and 'absent' in p.status
    assert p.process_iq(np.zeros(100,np.complex64),100)==[]
    assert p.finish()==[]


def test_modulation_filter_and_integrity_unknown():
    p=ISM433Plugin();p.configure(1000000,433920000,433920000,{'modulation':'fsk'})
    p.origin=100
    p.output.put({'model':'OOK device','mod':'ASK','time':'@0.1s'})
    p.output.put({'model':'FSK device','mod':'FSK','time':'@0.2s','codes':['{12}abc']})
    frames=p._frames()
    assert len(frames)==1 and frames[0].raw==bytes.fromhex('abc0')
    assert frames[0].crc_ok is None and frames[0].timestamp==pytest.approx(100.2)
    assert frames[0].fields['PHY']['raw_bit_length']==12


def test_decoder_selection_validation():
    assert protocol_ids('19, 76;19')==[19,76]
    with pytest.raises(ValueError):protocol_ids('19 -F mqtt://host')


def test_legacy_and_independent_settings(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'PROFILE',tmp_path)
    (tmp_path/'settings.json').write_text(json.dumps({'gain':47,'center':2405000000,'channel':11}),encoding='utf8')
    assert config.load().gain==47 and config.load().channel==11
    for band,gain in [('ism433',23),('ism868',37)]:
        settings=config.load(band);settings.gain=gain;settings.channel_width=120000;config.save(settings)
    assert config.load().gain==47
    assert config.load('ism433').gain==23 and config.load('ism868').gain==37
    assert config.load('ism433').sample_rate==1000000
