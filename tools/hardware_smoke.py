import time,json
from sdr_debug.sdr.backends import Settings
from sdr_debug.dsp.engine import Engine
s=Settings(backend='PlutoSDR',uri='usb:1.19.5',center=2425e6,sample_rate=4000000)
e=Engine();e.start(s)
start=time.monotonic();events=[]
while time.monotonic()-start<8:
    while not e.events.empty():
        kind,value=e.events.get()
        events.append((kind,value.public() if kind=='settings' else value))
    if e.stop_event.is_set():break
    time.sleep(.1)
e.stop()
for t in e.threads:t.join(4)
print(json.dumps({'events':events,'counts':e.counts,'spectrum':bool(e.spectra),'threads_stopped':not any(t.is_alive() for t in e.threads)},indent=2,ensure_ascii=False))
