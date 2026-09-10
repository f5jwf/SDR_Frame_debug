"""Optional long-running bounded-queue smoke test (demo by default)."""
import argparse
import json
import time
from sdr_debug.dsp.engine import Engine
from sdr_debug.sdr.backends import Settings

parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=60)
args=parser.parse_args();engine=Engine();engine.start(Settings(backend='Démonstration'))
start=time.monotonic();last=start
try:
    while time.monotonic()-start<args.seconds and not engine.stop_event.is_set():
        while not engine.frames.empty():engine.frames.get_nowait()
        if time.monotonic()-last>30:
            print(json.dumps(engine.counts),flush=True);last=time.monotonic()
        time.sleep(.02)
finally:
    engine.stop()
    for t in engine.threads:t.join(5)
    print(json.dumps({'seconds':time.monotonic()-start,'counts':engine.counts,'stopped':not any(t.is_alive() for t in engine.threads)}))
