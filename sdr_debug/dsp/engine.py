"""Two workers, bounded queues and explicit discontinuities; no GUI I/O."""
from collections import deque
from dataclasses import replace
import logging
import multiprocessing
import queue
import threading
import time
import numpy as np
from ..sdr.backends import open_source
from ..protocols.registry import available
from ..capture.iq import Recorder
from .spectrum import Spectrum
from ..sdr.rates import usable_bandwidth

log=logging.getLogger(__name__)


class Engine:
    def __init__(self,isolated=False):
        self.isolated=isolated; self.ready=None; self.child=None
        self.dsp_done=threading.Event()
        self.stop_event=threading.Event(); self.blocks=queue.Queue(64); self.commands=queue.Queue(4)
        self.frames=queue.Queue(2000); self.events=queue.Queue(64); self.spectra=deque(maxlen=1)
        self._counts={'total':0,'ok':0,'bad':0,'dropped_blocks':0,'dropped_frames':0,'restarts':0}
        self.gain_commands=queue.Queue(1); self.metrics=deque(maxlen=1); self.throughput=deque(maxlen=1); self.performance=deque(maxlen=1)
        self.threads=[]; self.record_path=None; self.record_lock=threading.Lock()
    @property
    def counts(self):return dict(self._counts.items())
    def increment(self,key):
        if hasattr(self._counts,"increment"):self._counts.increment(key)
        else:self._counts[key]+=1
    def event(self,kind,value):
        try: self.events.put_nowait((kind,value))
        except queue.Full: pass
    def start(self,settings,options=None):
        if any(t.is_alive() for t in self.threads): raise RuntimeError('Réception déjà active')
        self.settings=replace(settings); self.options=dict(options or {})
        self.dsp_done.clear()
        if self.isolated:
            from .process_worker import run_dsp,SharedCounts,KEYS
            ctx=multiprocessing.get_context('spawn')
            self.stop_event=ctx.Event(); self.ready=ctx.Event(); self.dsp_done=ctx.Event()
            from .shared_queue import IQQueue
            self.blocks=IQQueue(ctx); self.results=ctx.Queue(128); self.remote_frames=ctx.Queue(2000)
            values=ctx.Array('q',len(KEYS)); self._counts=SharedCounts(values)
            self.child=ctx.Process(target=run_dsp,args=(self.blocks,self.results,self.remote_frames,self.stop_event,values,self.ready,self.dsp_done),name='SDR-DSP',daemon=True)
            self.child.start()
            acquisition=threading.Thread(target=self.acquire,daemon=True,name='SDR')
            bridge=threading.Thread(target=self.bridge,daemon=True,name='DSP-results')
            self.threads=[acquisition,bridge,self.child]
            acquisition.start();bridge.start()
        else:
            from .kernels import warmup
            warmup()
            self.plugin_types=available();self.stop_event.clear()
            self.threads=[threading.Thread(target=self.acquire,daemon=True,name='SDR'),threading.Thread(target=self.dsp,daemon=True,name='DSP')]
            for thread in self.threads:thread.start()

    def bridge(self):
        stopped=False
        while True:
            for _ in range(256):
                try:frame=self.remote_frames.get_nowait()
                except queue.Empty:break
                try:self.frames.put_nowait(frame)
                except queue.Full:self.increment('dropped_frames')
            try:kind,value=self.results.get(timeout=.01)
            except queue.Empty:
                if not self.child.is_alive():break
                continue
            if kind=='spectrum':self.spectra.append(value)
            elif kind=='metrics':self.metrics.append(value)
            elif kind=='performance':self.performance.append(value)
            elif kind=='stopped':stopped=True
            else:self.event(kind,value)
        if not stopped and not self.stop_event.is_set():
            self.event('error',f'Le processus DSP a quitté prématurément (code {self.child.exitcode})')
        self.stop_event.set();self.dsp_done.set()
        self.threads[0].join()
        self.event('stopped',None)
        # Avoid hanging shutdown if a failed worker left the feeder undrained.
        self.blocks.cancel_join_thread()
        for channel in (self.blocks,self.results,self.remote_frames):channel.close()

    def stop(self): self.stop_event.set()
    def reconfigure(self,settings,options=None):
        try: self.commands.put_nowait((replace(settings),dict(options or {})))
        except queue.Full: self.event('error','Trop de changements : réessayer dans un instant')
    def set_gain(self, gain, agc):
        # Latest request wins while the operator turns the control.
        try: self.gain_commands.get_nowait()
        except queue.Empty: pass
        self.gain_commands.put_nowait((gain,agc))
    def recording(self,path):
        with self.record_lock: self.record_path=path
    def acquire(self):
        source=None; recorder=None; active_path=None; serial=0; generation=0
        try:
            if self.ready is not None:
                while not self.ready.wait(.05):
                    if self.stop_event.is_set():return
                if self.stop_event.is_set():return
            source=open_source(self.settings); self.event('settings',replace(self.settings))
            deadline=time.monotonic(); last_gain=0.; transfer_start=time.monotonic(); transferred=0
            while not self.stop_event.is_set():
                try: settings,options=self.commands.get_nowait()
                except queue.Empty: pass
                else:
                    if recorder: recorder.close(); recorder=None
                    self.recording(None); active_path=None
                    source.close(); source=None
                    self.settings=settings; self.options=options
                    source=open_source(settings); generation+=1; self.increment('restarts')
                    self.event('settings',replace(settings)); deadline=time.monotonic(); transfer_start=deadline; transferred=0
                try: gain,agc=self.gain_commands.get_nowait()
                except queue.Empty: pass
                else:
                    try:
                        if not hasattr(source,'set_gain'):
                            raise ValueError('Gain direct disponible sur PlutoSDR ; utiliser Appliquer pour RTL.')
                        state=source.set_gain(gain,agc)
                        if recorder: recorder.note_gain(state)
                        self.event('gain',state)
                        last_gain=time.monotonic()
                    except Exception as exc:
                        self.event('error',f'Réglage du gain : {exc}')
                if hasattr(source,'gain_state') and time.monotonic()-last_gain>=.5:
                    state=source.gain_state(); self.event('gain',state); last_gain=time.monotonic()
                with self.record_lock: path=self.record_path
                if path!=active_path:
                    if recorder: recorder.close(); recorder=None
                    if path: recorder=Recorder(path,self.settings)
                    active_path=path; self.event('recording',bool(path))
                iq,ts=source.read()
                transferred+=len(iq)
                elapsed=time.monotonic()-transfer_start
                if elapsed>=1:
                    self.throughput.append((transferred/elapsed,self.settings.sample_rate))
                    transfer_start=time.monotonic(); transferred=0
                if recorder: recorder.write(iq,ts)
                item=(generation,serial,replace(self.settings),dict(self.options),iq,ts)
                serial+=1
                try: self.blocks.put_nowait(item)
                except queue.Full: self.increment('dropped_blocks')
                if self.settings.backend in ('Démonstration','Rejeu SigMF'):
                    deadline+=len(iq)/self.settings.sample_rate
                    self.stop_event.wait(max(0,deadline-time.monotonic()))
        except EOFError:
            self.event('info','Fin du rejeu')
        except Exception as exc:
            log.exception('Acquisition interrompue')
            self.event('error',str(exc))
        finally:
            if recorder:
                try: recorder.close()
                except Exception: log.exception('Fermeture capture')
            if source:
                try: source.close()
                except Exception: log.exception('Fermeture SDR')
            self.stop_event.set(); self.event('recording',False)
            # FIFO sentinel follows every accepted block, including MP feeder data.
            while not self.dsp_done.is_set():
                try:self.blocks.put(None,timeout=.1);break
                except queue.Full:continue
    def publish_frames(self,frames):
        for frame in frames:
            self.increment('total')
            if frame.crc_ok is not None:self.increment('ok' if frame.crc_ok else 'bad')
            try:self.frames.put_nowait(frame)
            except queue.Full:self.increment('dropped_frames')

    def dsp(self):
        previous=None; generation=None; plugin=None; analyzer=None; analysis_key=None; last_fft=0; perf_start=time.monotonic(); busy=0.; samples=0; blocks=0; worst=0.
        try:
            while True:
                try:item=self.blocks.get(timeout=.1)
                except queue.Empty:continue
                if item is None:break
                gen,serial,s,options,iq,ts=item
                work_start=time.perf_counter()
                if gen!=generation or previous is None:
                    if plugin is not None and hasattr(plugin,"finish"):self.publish_frames(plugin.finish())
                    plugin=self.plugin_types[s.protocol]()
                    frequency=s.rx_frequency if s.workspace!='zigbee' else plugin.channels.get(s.channel,s.center)
                    plugin.configure(s.sample_rate,s.center,frequency,{**options,"rf_bandwidth":usable_bandwidth(s)})
                    generation=gen; analyzer=None
                    self.event('decode_status',getattr(plugin,'status',None) or ('Décodage actif' if getattr(plugin,'enabled',True) else 'Spectre seul : choisir une cadence proposée et placer le canal entier dans la bande RF'))
                elif serial!=previous+1:
                    if hasattr(plugin,"reset_stream"):plugin.reset_stream()
                    else:plugin.configure(s.sample_rate,s.center,plugin.channels.get(s.channel,s.center),{**options,"rf_bandwidth":usable_bandwidth(s)})
                    analyzer=None
                previous=serial
                # The external ISM decoder must receive the samples as acquired.
                # Removing the mean one block at a time creates a notch at the
                # tuning frequency and can erase a narrow OOK/FSK transmission
                # which is otherwise perfectly visible in the FFT.
                self.publish_frames(plugin.process_iq(iq,ts))
                display_iq=iq-iq.mean() if s.dc else iq
                key=(s.fft_size,s.window,s.average,s.gain,s.agc)
                if analyzer is None or key!=analysis_key:
                    analyzer=Spectrum(s.fft_size,s.window,s.average); analysis_key=key
                analyzer.feed(display_iq)
                now=time.monotonic()
                if now-last_fft >= s.waterfall_ms/1000:
                    snapshot=analyzer.snapshot(s.spectrum_mode)
                    if snapshot is None: continue
                    power,metrics=snapshot
                    axis=np.fft.fftshift(np.fft.fftfreq(s.fft_size,1/s.sample_rate))+s.center
                    self.spectra.append((axis,power,ts,s.sample_rate,s.center))
                    self.metrics.append(metrics)
                    last_fft=now
                duration=time.perf_counter()-work_start
                busy+=duration; worst=max(worst,duration); samples+=len(iq); blocks+=1
                if time.monotonic()-perf_start>=1:
                    self.performance.append({'dsp_ms_per_block':1000*busy/blocks,'dsp_max_ms':1000*worst,
                                             'signal_ms_per_block':1000*samples/s.sample_rate/blocks,
                                             'queue_blocks':self.blocks.qsize(),'queue_capacity':getattr(self.blocks,'maxsize',64)})
                    perf_start=time.monotonic(); busy=0.; samples=0; blocks=0; worst=0.
        except Exception as exc:
            log.exception('DSP interrompu'); self.event('error',str(exc)); self.stop_event.set()
        finally:
            try:
                if plugin is not None and hasattr(plugin,'finish'):self.publish_frames(plugin.finish())
            except Exception as exc:self.event('error',f'Fermeture décodeur : {exc}')
            self.dsp_done.set();self.event('stopped',None)
