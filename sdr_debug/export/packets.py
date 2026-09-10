import csv
import json
import struct
import math
from pathlib import Path
from dataclasses import asdict


def record(frame):
    out=asdict(frame); out['raw']=frame.raw.hex()
    if not math.isfinite(frame.level):out['level']=None
    return out


def export_frames(path, frames, metadata=None):
    path=Path(path); ext=path.suffix.lower()
    if ext=='.pcap':
        if any(frame.protocol!='zigbee' for frame in frames):
            raise ValueError('PCAP IEEE 802.15.4 réservé aux trames Zigbee ; utiliser JSON ou CSV pour ISM')
        with path.open('wb') as f:
            # LINKTYPE_IEEE802_15_4_WITHFCS (195), little-endian PCAP.
            f.write(struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,127,195))
            for frame in frames:
                sec=int(frame.timestamp); usec=int((frame.timestamp-sec)*1e6)
                f.write(struct.pack('<IIII',sec,usec,len(frame.raw),len(frame.raw))); f.write(frame.raw)
    elif ext=='.csv':
        with path.open('w',newline='',encoding='utf-8-sig') as f:
            columns=['timestamp','protocol','channel','frequency','level','crc_ok','summary','raw','favorite']
            writer=csv.DictWriter(f,columns,extrasaction='ignore'); writer.writeheader()
            for frame in frames: writer.writerow(record(frame))
    else:
        path.write_text(json.dumps({'metadata':metadata or {},'frames':[record(f) for f in frames]},indent=2,ensure_ascii=False),encoding='utf8')
