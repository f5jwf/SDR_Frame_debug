"""Process-safe adapters for the DSP worker; GUI queues remain local."""
import queue

KEYS=('total','ok','bad','dropped_blocks','dropped_frames','restarts')


class SharedCounts:
    def __init__(self,values):self.values=values
    def __getitem__(self,key):return self.values[KEYS.index(key)]
    def __setitem__(self,key,value):self.values[KEYS.index(key)]=value
    def increment(self,key):
        with self.values.get_lock():self.values[KEYS.index(key)]+=1
    def items(self):
        with self.values.get_lock():return list(zip(KEYS,self.values[:]))


class ResultSink:
    def __init__(self,out,kind):self.out=out;self.kind=kind
    def append(self,value):
        try:self.out.put_nowait((self.kind,value))
        except queue.Full:pass  # Only disposable display/telemetry snapshots.


def run_dsp(blocks,results,frames,stop,counts,ready,done):
    from .engine import Engine
    from ..protocols.registry import available
    worker=Engine()
    worker.blocks=blocks;worker.events=results;worker.frames=frames
    worker.stop_event=stop;worker.dsp_done=done;worker._counts=SharedCounts(counts)
    worker.spectra=ResultSink(results,'spectrum')
    worker.metrics=ResultSink(results,'metrics')
    worker.performance=ResultSink(results,'performance')
    try:
        from .kernels import warmup
        warmup()
        worker.plugin_types=available();ready.set()
        import os
        if os.environ.get("SDR_DSP_PROFILE"):
            import cProfile
            profile=cProfile.Profile();profile.runcall(worker.dsp);profile.dump_stats(os.environ["SDR_DSP_PROFILE"])
        else:worker.dsp()
    except Exception as exc:
        worker.event('error',f'DSP process: {exc}');stop.set();ready.set();done.set()
