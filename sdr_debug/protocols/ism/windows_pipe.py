"""A byte-mode named pipe opened by rtl_433 as a binary input file.

Some Windows builds leave stdin in CRT text mode, corrupting float IQ at 0x1a.
Named input files use fopen(..., "rb") and preserve every sample byte.
"""
import ctypes
from ctypes import wintypes
import uuid


class BinaryPipe:
    def __init__(self,rate,frequency):
        self.name=rf'\\.\pipe\sdr_{frequency/1e6:g}M_{rate/1000:g}k_{uuid.uuid4().hex}.cf32'
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateNamedPipeW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
        self.api.CreateNamedPipeW.restype=wintypes.HANDLE
        self.api.ConnectNamedPipe.argtypes=[wintypes.HANDLE,ctypes.c_void_p]
        self.api.WriteFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
        self.api.FlushFileBuffers.argtypes=[wintypes.HANDLE]
        self.api.CloseHandle.argtypes=[wintypes.HANDLE]
        self.handle=self.api.CreateNamedPipeW(self.name,2,0,1,1024*1024,1024*1024,0,None)
        if self.handle==wintypes.HANDLE(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        self.connected=False
    def connect(self):
        if not self.api.ConnectNamedPipe(self.handle,None) and ctypes.get_last_error()!=535:
            raise ctypes.WinError(ctypes.get_last_error())
        self.connected=True
    def write(self,data):
        value=bytes(data);buffer=ctypes.create_string_buffer(value);count=wintypes.DWORD()
        if not self.api.WriteFile(self.handle,buffer,len(value),ctypes.byref(count),None):
            raise ctypes.WinError(ctypes.get_last_error())
        return count.value
    def close(self):
        if self.handle is None:return
        if self.connected:self.api.FlushFileBuffers(self.handle)
        self.api.CloseHandle(self.handle);self.handle=None
