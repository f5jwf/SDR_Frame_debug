import json
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
import numpy as np


class Recorder:
    def __init__(self,path,settings):
        self.base=Path(path).with_suffix(''); self.settings=replace(settings); self.count=0; self.captures=[]; self.annotations=[]
        self.stream=self.base.with_suffix('.sigmf-data').open('xb')
        self.write_meta()
    def write_meta(self):
        meta={'global':{'core:datatype':'cf32_le','core:sample_rate':self.settings.sample_rate,
              'core:version':'1.2.5','core:description':'SDR Frame Debug RX',
              'sdr_debug:settings':self.settings.public()},'captures':self.captures,'annotations':self.annotations}
        self.base.with_suffix('.sigmf-meta').write_text(json.dumps(meta,indent=2),encoding='utf8')
    def write(self,iq,timestamp):
        if not self.captures:
            self.captures.append({'core:sample_start':0,'core:frequency':self.settings.center,
                                 'core:datetime':datetime.fromtimestamp(timestamp,timezone.utc).isoformat()})
            self.write_meta()
        self.stream.write(np.asarray(iq,dtype='<c8').tobytes()); self.count+=len(iq)
    def note_gain(self,state):
        self.annotations.append({'core:sample_start':self.count,'core:label':f"RX gain {state['gain']} dB; mode {state['mode']}"})
        self.write_meta()
    def close(self): self.stream.close(); self.write_meta()


class Replay:
    def __init__(self,settings):
        base=Path(settings.replay).with_suffix('')
        meta=json.loads(base.with_suffix('.sigmf-meta').read_text(encoding='utf8'))
        if meta['global']['core:datatype']!='cf32_le': raise ValueError('Rejeu : format SigMF cf32_le requis')
        captures=meta.get('captures',[])
        if len(captures)!=1 or captures[0].get('core:sample_start')!=0:
            raise ValueError('Rejeu : une capture à fréquence fixe commençant à zéro est requise')
        settings.rf_bandwidth=float(meta['global'].get('sdr_debug:settings',{}).get('rf_bandwidth',0))
        settings.sample_rate=int(meta['global']['core:sample_rate']); settings.center=captures[0]['core:frequency']
        self.start=datetime.fromisoformat(captures[0]['core:datetime'].replace('Z','+00:00')).timestamp()
        path=base.with_suffix('.sigmf-data')
        if path.stat().st_size%8: raise ValueError('Fichier I/Q tronqué')
        self.stream=path.open('rb'); self.pos=0; self.settings=settings
    def read(self):
        iq=np.frombuffer(self.stream.read(32768*8),dtype='<c8').copy()
        if not len(iq): raise EOFError('Fin du rejeu')
        ts=self.start+self.pos/self.settings.sample_rate; self.pos+=len(iq)
        return iq,ts
    def close(self): self.stream.close()
