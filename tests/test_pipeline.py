import queue
import time
import numpy as np
import pytest
from scipy.signal import lfilter
from sdr_debug.dsp.fir import StreamingFIR
from sdr_debug.dsp.engine import Engine
from sdr_debug.sdr.backends import Settings
from sdr_debug.capture.iq import Recorder
from sdr_debug.protocols.zigbee.plugin import ZigbeePlugin
from sdr_debug.protocols.zigbee.phy import modulate,with_fcs


@pytest.mark.parametrize("down",[1,2])
def test_batched_fir_matches_causal_filter_across_odd_blocks(down):
    rng=np.random.default_rng(35)
    iq=(rng.normal(size=23071)+1j*rng.normal(size=23071)).astype(np.complex64)
    taps=rng.normal(size=33).astype(np.float32)
    fir=StreamingFIR(taps,down);parts=[];pos=0
    for size in [1,7,997,8192,13874]:
        block=iq[pos:pos+size];out,offset=fir.process(block)
        assert offset==(-pos)%down
        parts.append(out);pos+=len(block)
    expected=lfilter(taps,np.array([1],np.float32),iq)[::down]
    np.testing.assert_allclose(np.concatenate(parts),expected,atol=1e-5,rtol=2e-6)


def test_gap_reset_preserves_filters_and_clears_partial_packet():
    raw=with_fcs(bytes.fromhex('4188013412000078560800000078561e010001060004010101010101'))
    p=ZigbeePlugin();p.configure(4000000,2425e6,2425e6,{})
    wave=modulate(raw)
    p.process_iq(wave[:1500],100)
    kernel=p.fir.kernel;templates=p.phy.template_ffts
    p.reset_stream()
    assert p.fir.kernel is kernel and p.phy.template_ffts is templates
    frames=p.process_iq(np.concatenate((np.zeros(100),wave,np.zeros(2000))),200)
    assert [f.raw for f in frames]==[raw]
    assert frames[0].crc_ok and abs(frames[0].timestamp-200.000025)<3e-6


def join_engine(engine):
    deadline=time.monotonic()+15
    for worker in engine.threads:worker.join(max(0,deadline-time.monotonic()))
    assert not any(worker.is_alive() for worker in engine.threads)


def test_isolated_replay_drains_every_packet_at_eof(tmp_path):
    raws=[with_fcs(bytes.fromhex('0200')+bytes([i])) for i in range(20)]
    iq=np.concatenate([np.concatenate((np.zeros(97),modulate(raw),np.zeros(101))) for raw in raws])
    path=tmp_path/'capture.sigmf-meta'
    recorder=Recorder(path,Settings());recorder.write(iq,100);recorder.close()
    engine=Engine(isolated=True)
    engine.start(Settings(backend='Rejeu SigMF',replay=str(path)))
    join_engine(engine)
    received=[]
    while not engine.frames.empty():received.append(engine.frames.get_nowait().raw)
    assert received==raws
    assert engine.counts['ok']==20 and engine.counts['dropped_blocks']==0


@pytest.mark.parametrize("failure",['stop','source','dsp'])
def test_isolated_early_stop_and_failures_terminate(failure):
    engine=Engine(isolated=True)
    settings=Settings(backend='invalid' if failure=='source' else 'Démonstration',protocol='invalid' if failure=='dsp' else 'zigbee')
    engine.start(settings)
    if failure=='stop':engine.stop()
    join_engine(engine)
    events=[]
    while not engine.events.empty():events.append(engine.events.get_nowait()[0])
    assert 'stopped' in events
    if failure!='stop':assert 'error' in events


def test_compiled_phase_and_correlation_match_reference():
    from sdr_debug.dsp.kernels import phase_difference,correlation_scores
    rng=np.random.default_rng(26)
    iq=(rng.normal(size=18001)+1j*rng.normal(size=18001)).astype(np.complex64)
    expected=np.angle(iq[1:]*iq[:-1].conj())
    np.testing.assert_allclose(phase_difference(iq),expected,atol=5e-7)
    length=635;d=expected.astype(np.float64)
    sums=np.concatenate(([0.],np.cumsum(d)));squares=np.concatenate(([0.],np.cumsum(d*d)))
    variance=squares[length:]-squares[:-length]-(sums[length:]-sums[:-length])**2/length
    target=rng.uniform(.5,1.,size=len(variance)).astype(np.float32)
    corr=(target*np.sqrt(variance*300.)).astype(np.float32)
    scores=correlation_scores(expected,corr,length,300.)
    reference=corr/np.sqrt(variance*300.);reference[reference<.78]=0
    np.testing.assert_allclose(scores,reference,atol=1e-6)


def test_shared_iq_queue_bounds_and_slot_reuse():
    import multiprocessing
    from sdr_debug.dsp.shared_queue import IQQueue
    q=IQQueue(multiprocessing.get_context('spawn'),capacity=2,samples=32)
    def item(serial):return (0,serial,Settings(),{},np.full(17,serial,np.complex64),100.)
    try:
        q.put_nowait(item(1));q.put_nowait(item(2))
        with pytest.raises(queue.Full):q.put_nowait(item(3))
        first=q.get(timeout=2);q.put_nowait(item(3))
        second=q.get(timeout=2);third=q.get(timeout=2)
        for expected,value in enumerate([first,second,third],1):
            assert value[1]==expected
            np.testing.assert_array_equal(value[4],np.full(17,expected,np.complex64))
        q.put(None);assert q.get(timeout=2) is None
    finally:q.close()
