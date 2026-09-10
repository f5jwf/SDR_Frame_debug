"""IEEE 802.15.4 2.4 GHz half-sine O-QPSK receiver.

Differential matched templates remove carrier phase ambiguity. The SHR fixes
sample timing and estimates constant CFO. Streaming overlap preserves packets
across blocks. This Python reference PHY is intended for diagnostic use.
"""
import numpy as np
from scipy import signal, fft
from ...dsp.kernels import correlation_scores,decode_bytes,phase_difference

# c0 first (IEEE 802.15.4 2.4 GHz symbol-to-chip mapping).
CHIPS = np.array([[int(c) for c in s] for s in (
    '11011001110000110101001000101110', '11101101100111000011010100100010',
    '00101110110110011100001101010010', '00100010111011011001110000110101',
    '01010010001011101101100111000011', '00110101001000101110110110011100',
    '11000011010100100010111011011001', '10011100001101010010001011101101',
    '10001100100101100000011101111011', '10111000110010010110000001110111',
    '01111011100011001001011000000111', '01110111101110001100100101100000',
    '00000111011110111000110010010110', '01100000011101111011100011001001',
    '10010110000001110111101110001100', '11001001011000000111011110111000',
)], dtype=np.int8)
FS = 4_000_000
SPS = 64


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc


def with_fcs(data):
    return data + crc16(data).to_bytes(2, 'little')


def modulate_symbols(symbols):
    chips = CHIPS[np.asarray(symbols)].ravel() * 2 - 1
    out = np.zeros(len(chips) * 2 + 2, dtype=np.complex64)
    pulse = np.sin(np.pi * np.arange(4) / 4)
    for parity, factor in ((0, 1), (1, 1j)):
        impulses = np.zeros(len(out), dtype=np.float32)
        indices = np.arange(parity, len(chips), 2) * 2
        impulses[indices] = chips[parity::2]
        out += factor * signal.lfilter(pulse, [1], impulses)
    return out


def modulate(psdu):
    packet = b'\x00' * 4 + b'\xa7' + bytes([len(psdu)]) + psdu
    symbols = [n for b in packet for n in (b & 15, b >> 4)]
    return modulate_symbols(symbols)


def differential(iq):
    return phase_difference(np.asarray(iq,dtype=np.complex64))


class ZigbeePHY:
    def __init__(self):
        self.buffer = np.empty(0, np.complex64)
        self.start_time = 0.0
        self.shr = differential(modulate_symbols([0]*8 + [7, 10]))[4:639]
        self.template = self.shr - self.shr.mean()
        self.template_energy = np.sum(self.template**2)
        self.symbols = np.array([differential(modulate_symbols([i]))[4:63] for i in range(16)])
        self.cursor = 0
        self.template_ffts = {}

    def feed(self, iq, timestamp):
        if not len(self.buffer):
            self.start_time = timestamp
        self.buffer = np.concatenate((self.buffer, iq))
        frames = []
        d = differential(self.buffer)
        length = len(self.template)
        if len(d) < length + 4:
            return frames
        fft_size=2048
        if fft_size not in self.template_ffts:
            self.template_ffts[fft_size]=fft.rfft(self.template[::-1],fft_size)
        step=fft_size-length+1; valid_count=len(d)-length+1
        count=(valid_count+step-1)//step
        padded=np.pad(d,(0,count*step+length-1-len(d)))
        chunks=np.lib.stride_tricks.sliding_window_view(padded,fft_size)[::step]
        transformed=fft.rfft(chunks,axis=1);transformed*=self.template_ffts[fft_size]
        corr=fft.irfft(transformed,axis=1)[:,length-1:].ravel()[:valid_count]
        score=correlation_scores(d,corr,length,float(self.template_energy))
        peaks, _ = signal.find_peaks(score, height=0.78, distance=64)
        consumed = 0
        retain = max(0, len(self.buffer)-1024)
        for peak in peaks:
            start = int(peak) - 4
            if start < max(self.cursor, 0):
                continue
            if len(d) < start + 12*SPS:
                retain = min(retain,start)
                break
            cfo = float(np.mean(d[peak:peak+length] - self.shr))
            phr=int(decode_bytes(d,start+10*SPS,1,cfo,self.symbols)[0])
            if not 5 <= phr <= 127:
                self.cursor = start + SPS
                continue
            end = start + (12+2*phr)*SPS
            if len(d) < end:
                retain = min(retain,start)
                break
            raw = decode_bytes(d,start+12*SPS,phr,cfo,self.symbols).tobytes()
            power = 10*np.log10(float(np.mean(abs(self.buffer[start:end])**2))+1e-20)
            frames.append((self.start_time+start/FS, raw, power, cfo*FS/(2*np.pi)))
            self.cursor = end
            consumed = end
        # Retain enough overlap for a maximum-length packet, never unbounded.
        trim = max(consumed, retain, len(self.buffer)-18_000)
        if trim > 0:
            self.buffer = self.buffer[trim:]
            self.start_time += trim/FS
            self.cursor = max(0, self.cursor-trim)
        return frames
