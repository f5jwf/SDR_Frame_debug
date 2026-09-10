import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
import numpy as np
from scipy.signal import firwin
from ...dsp.fir import StreamingFIR
from ...dsp.resample import Resampler
from ..base import Frame


class UnknownOOKDetector:
    """Keep strong, well-formed OOK bursts visible when no device decoder knows them."""
    def __init__(self, rate, frequency):
        self.rate=rate;self.frequency=frequency;self.state=False;self.run=0
        self.segments=[];self.started=None

    def _emit(self, timestamp):
        parts=self.segments;self.segments=[];self.started=None
        active=sum(length for state,length in parts if state)
        duration=sum(length for _,length in parts)
        if active<self.rate*.001 or duration<self.rate*.02 or len(parts)<10 or duration>self.rate*.5:return None
        raw=b''.join(bytes([int(state)])+min(65535,round(length*1e6/self.rate)).to_bytes(2,'big') for state,length in parts[:256])
        details={'PHY':{'modulation':'OOK/ASK','integrity':'non renseignée','raw_pulse_count':len(parts),
                        'duration_ms':1000*duration/self.rate,'raw_bit_length':None},
                 'generic_ook':{'segments_us':[(int(state),round(length*1e6/self.rate)) for state,length in parts[:256]]}}
        return Frame(self.started if self.started is not None else timestamp,1,self.frequency,raw,None,float('nan'),details,
                     f'OOK inconnu · {len(parts)} impulsions · {1000*duration/self.rate:.1f} ms',protocol='ism-ook-raw')

    def feed(self, iq, timestamp):
        noise=np.percentile(np.abs(iq),20); threshold=max(.002,noise*8)
        levels=np.abs(iq)>threshold;frames=[];offset=0
        changes=np.flatnonzero(levels[1:]!=levels[:-1])+1
        for end in np.append(changes,len(levels)):
            state=bool(levels[offset]);length=int(end-offset);offset=int(end)
            if state and not self.segments:self.started=timestamp+(end-length)/self.rate
            if self.segments or state:self.segments.append((state,length))
            if not state and self.segments and length>=round(.003*self.rate):
                # The final silence is a delimiter, not a part of the packet.
                self.segments.pop();frame=self._emit(timestamp+end/self.rate)
                if frame:frames.append(frame)
        return frames

    def finish(self, timestamp):
        frame=self._emit(timestamp)
        return [frame] if frame else []


def executable(explicit=''):
    if explicit:
        path=Path(explicit).expanduser()
        return str(path) if path.is_file() else None
    found=shutil.which('rtl_433')
    if found:return found
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[3]
    for name in ('rtl_433.exe','rtl_433_64bit_static.exe'):
        path=root/'runtime'/'rtl_433'/name
        if path.is_file():return str(path)
    return None


def protocol_ids(text):
    if not text.strip():return []
    values=re.split(r'[,;\s]+',text.strip())
    if any(not v.isdigit() or not 1<=int(v)<=9999 for v in values):
        raise ValueError('Les décodeurs doivent être des numéros positifs séparés par des virgules')
    return list(dict.fromkeys(int(v) for v in values))


class ISMPlugin:
    bandwidth=200000
    min_sample_rate=1000000
    rate=1000000

    def configure(self,sample_rate,center_frequency,channel_frequency,options=None):
        self.options=options or {};self.frequency=float(self.options.get('rx_frequency',channel_frequency))
        self.width=float(self.options.get('channel_width',self.bandwidth))
        self.bandwidth=self.width;self.input_rate=float(sample_rate)
        self.phase=0.;self.oscillator=None;self.step=2*np.pi*(self.frequency-center_frequency)/self.input_rate
        nominal=round(sample_rate/1000)*1000 if abs(sample_rate-round(sample_rate/1000)*1000)<=4 else int(sample_rate)
        self.resampler=None if nominal==self.rate else Resampler(nominal,self.rate)
        self.fir=StreamingFIR(firwin(65,self.width/2,fs=self.rate).astype(np.float32))
        self.process=None;self.output=queue.Queue(2000);self.errors=deque(maxlen=8);self.origin=None
        self.carried=[];self.finished=False;self.output_overflow=False;self.input_error=None
        self.generic_ook=UnknownOOKDetector(self.rate,self.frequency) if self.options.get('modulation','auto') in ('auto','ook') else None
        if self.options.get("fsk_detector","classic") not in ("classic","minmax","auto"):raise ValueError("Détecteur FSK inconnu")
        path=executable(self.options.get('rtl433_path',''))
        self.enabled=bool(path) and abs(self.frequency-center_frequency)+self.width/2<=min(sample_rate,self.options.get('rf_bandwidth') or sample_rate)/2
        if not path:self.status='Spectre actif · rtl_433 absent : installer via tools/install_rtl433.py ou sélectionner son exécutable'
        elif not self.enabled:self.status='Spectre actif · Canal hors bande : recentrer sur RX'
        else:self.status='Décodage ISM actif · rtl_433 · OOK/ASK et FSK · appareils reconnus uniquement'
        self.path=path
        self.ids=protocol_ids(self.options.get('decoder_ids',''))

    def _start(self,timestamp):
        self.origin=timestamp
        self.binary_pipe=None
        source='cf32:-'
        if os.name=='nt':
            from .windows_pipe import BinaryPipe
            self.binary_pipe=BinaryPipe(self.rate,self.frequency);source=self.binary_pipe.name
        args=[self.path,'-c','0','-r',source,'-s',str(self.rate),'-f',str(int(self.frequency)),
              '-Y',self.options.get('fsk_detector','classic'),'-F','json','-M','time:rel','-M','protocol','-M','level','-M','bits']
        for ident in self.ids:args.extend(['-R',str(ident)])
        try:
            self.process=subprocess.Popen(args,stdin=subprocess.DEVNULL if self.binary_pipe else subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                          bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except Exception:
            if self.binary_pipe:self.binary_pipe.close()
            raise
        self.input=queue.Queue(8)
        self.readers=[threading.Thread(target=self._read,daemon=True),threading.Thread(target=self._errors,daemon=True)]
        self.writer=threading.Thread(target=self._write,daemon=True)
        for thread in self.readers+[self.writer]:thread.start()

    def _write(self):
        stream=self.binary_pipe or self.process.stdin
        try:
            if self.binary_pipe:self.binary_pipe.connect()
            while True:
                data=self.input.get()
                if data is None:break
                view=memoryview(data)
                while view:
                    count=stream.write(view)
                    if not count:raise BrokenPipeError('rtl_433 input closed')
                    view=view[count:]
        except Exception as exc:
            self.input_error=str(exc)
            self.errors.append('Entrée I/Q : '+self.input_error)
        finally:
            try:stream.close()
            except OSError:pass

    def _read(self):
        for line in self.process.stdout:
            try:
                event=json.loads(line)
                if 'model' in event:self.output.put_nowait(event)
            except json.JSONDecodeError:continue
            except queue.Full:self.output_overflow=True

    def _errors(self):
        for line in self.process.stderr:
            message=line.decode('utf8','replace').strip()
            if message:self.errors.append(message)

    def _frames(self):
        frames=self.carried;self.carried=[]
        while True:
            try:event=self.output.get_nowait()
            except queue.Empty:break
            mod=str(event.get('mod','')).upper();wanted=self.options.get('modulation','auto')
            if wanted=='ook' and mod not in ('ASK','OOK'):continue
            if wanted=='fsk' and 'FSK' not in mod:continue
            relative=str(event.get('time','0')).strip('@s ')
            try:timestamp=self.origin+float(relative)
            except (ValueError,TypeError):timestamp=self.origin or 0.
            raw=b'';bits=None
            codes=event.get('codes',[])
            if isinstance(codes,str):codes=[codes]
            if codes:
                match=re.fullmatch(r'\{(\d+)\}([0-9a-fA-F]+)',str(codes[0]))
                if match:
                    bits=int(match[1]);value=match[2];raw=bytes.fromhex(value+('0' if len(value)%2 else ''))
            mic=str(event.get('mic',''))
            crc=True if mic.upper().startswith('CRC') else None
            details={'rtl_433':event,'PHY':{'modulation':mod or 'non renseignée','channel_width_Hz':self.width,
                                         'raw_bit_length':bits,'integrity':mic or 'non renseignée'}}
            summary=str(event['model'])
            for key in ('id','channel','temperature_C','humidity','pressure_hPa','battery_ok','state'):
                if key in event:summary+=f' · {key}={event[key]}'
            frames.append(Frame(timestamp,1,self.frequency,raw,crc,float('nan'),details,summary,protocol=self.id))
        return frames

    def process_iq(self,iq_block,timestamp):
        if not self.enabled:return []
        if self.output_overflow:raise RuntimeError("File de trames rtl_433 saturée ; résultats perdus")
        if self.input_error:raise RuntimeError('rtl_433 ne reçoit plus les I/Q : '+self.input_error)
        iq=np.asarray(iq_block,dtype=np.complex64)
        if self.step:
            if self.oscillator is None or len(self.oscillator)!=len(iq):
                self.oscillator=np.exp(-1j*self.step*np.arange(len(iq))).astype(np.complex64)
            iq=iq*self.oscillator*np.complex64(np.exp(-1j*self.phase))
            self.phase=(self.phase+self.step*len(iq))%(2*np.pi)
        delay=32/self.rate
        if self.resampler is not None:iq=self.resampler.process(iq);delay+=self.resampler.delay
        iq,_=self.fir.process(iq)
        if self.process is None:self._start(timestamp-delay)
        if self.process.poll() is not None:raise RuntimeError('rtl_433 arrêté : '+' / '.join(self.errors))
        try:self.input.put_nowait(np.asarray(iq,dtype='<c8').tobytes())
        except queue.Full:raise RuntimeError('rtl_433 ne suit plus le débit I/Q ; réduire la cadence')
        if self.input_error:raise RuntimeError('rtl_433 ne reçoit plus les I/Q : '+self.input_error)
        frames=self._frames()
        if self.generic_ook is not None:frames.extend(self.generic_ook.feed(iq,timestamp-delay))
        return frames

    def finish(self):
        if self.process is None or self.finished:return self._frames()
        self.finished=True
        try:
            self.input.put(None,timeout=1)
            self.process.wait(timeout=5)
        except (queue.Full,subprocess.TimeoutExpired):
            self.process.kill();self.process.wait(timeout=2)
        for thread in self.readers+[self.writer]:thread.join(1)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
            if stream is not None:stream.close()
        frames=self._frames()
        if self.generic_ook is not None:frames.extend(self.generic_ook.finish(self.origin or 0.))
        return frames

    def reset_stream(self):
        frames=self.finish();self.carried=frames
        self.process=None;self.origin=None;self.finished=False
        self.phase=0.;self.fir.history.fill(0);self.fir.total=0
        if self.resampler:
            self.resampler.tail=np.empty(0,np.complex64);self.resampler.origin=0;self.resampler.total=0;self.resampler.next_output=0

    def get_filters(self):return ['rtl_433.model','rtl_433.id','rtl_433.channel','rtl_433.protocol','rtl_433.mod','rtl_433.mic']
    def decode(self,frame):return frame.fields
    def format_summary(self,frame):return frame.summary


class ISM433Plugin(ISMPlugin):
    id='ism433';name='ISM 433 MHz · rtl_433';channels={1:433920000}


class ISM868Plugin(ISMPlugin):
    id='ism868';name='ISM 868 MHz · rtl_433';channels={1:868300000}
