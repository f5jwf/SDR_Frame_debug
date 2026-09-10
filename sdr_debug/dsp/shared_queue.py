"""Bounded single-producer IQ queue using reusable shared memory slots.

Only settings and slot indices travel through the Windows pipe. The consumer
copies a slot before releasing it, so plugins never observe overwritten IQ.
"""
import queue
import numpy as np


class IQQueue:
    def __init__(self,ctx,capacity=64,samples=131072):
        self.maxsize=capacity;self.samples=samples;self.next_slot=0
        self.storage=ctx.RawArray('f',capacity*samples*2)
        self.slots=ctx.BoundedSemaphore(capacity)
        self.metadata=ctx.Queue(capacity)
    def put(self,item,block=True,timeout=None):
        if item is None:return self.metadata.put(None,block,timeout)
        generation,serial,settings,options,iq,timestamp=item
        if len(iq)>self.samples:raise ValueError('Bloc I/Q supérieur à la capacité du tampon partagé')
        if not self.slots.acquire(block,timeout):raise queue.Full
        slot=self.next_slot
        try:
            target=np.frombuffer(self.storage,dtype=np.complex64).reshape(self.maxsize,self.samples)[slot]
            target[:len(iq)]=iq
            self.metadata.put((generation,serial,settings,options,slot,len(iq),timestamp),block,timeout)
            self.next_slot=(slot+1)%self.maxsize
        except BaseException:
            self.slots.release();raise
    def put_nowait(self,item):return self.put(item,False)
    def get(self,block=True,timeout=None):
        item=self.metadata.get(block,timeout)
        if item is None:return None
        generation,serial,settings,options,slot,count,timestamp=item
        try:
            source=np.frombuffer(self.storage,dtype=np.complex64).reshape(self.maxsize,self.samples)[slot]
            iq=source[:count].copy()
        finally:self.slots.release()
        return generation,serial,settings,options,iq,timestamp
    def qsize(self):return self.metadata.qsize()
    def empty(self):return self.metadata.empty()
    def cancel_join_thread(self):self.metadata.cancel_join_thread()
    def close(self):self.metadata.close()
