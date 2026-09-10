"""Create a reproducible synthetic capture; no RF transmission."""
from pathlib import Path
import numpy as np
from sdr_debug.protocols.zigbee.phy import modulate,with_fcs,FS
from sdr_debug.protocols.zigbee.plugin import ZigbeePlugin
from sdr_debug.sdr.backends import Settings
from sdr_debug.capture.iq import Recorder
from sdr_debug.export.packets import export_frames


def main():
    folder=Path(__file__).resolve().parents[1]/'examples';folder.mkdir(exist_ok=True)
    rng=np.random.default_rng(802154);parts=[np.zeros(1000)]
    for i in range(3):
        raw=with_fcs(bytes.fromhex('4188')+bytes([i])+bytes.fromhex('3412000078560800000078561e')+bytes([i])+bytes.fromhex('00010600040101')+bytes([i,1,i,i]))
        parts.extend((modulate(raw)*.5,np.zeros(5000)))
    iq=np.concatenate(parts).astype(np.complex64)
    iq*=np.exp(1j*(.8+2*np.pi*18000*np.arange(len(iq))/FS))
    iq+=.008*(rng.normal(size=len(iq))+1j*rng.normal(size=len(iq)))
    rec=Recorder(folder/'zigbee_reference.sigmf-meta',Settings(backend='Démonstration'))
    rec.write(iq,1788861600.0);rec.close()
    plugin=ZigbeePlugin();plugin.configure(FS,2425e6,2425e6,{})
    frames=plugin.process_iq(iq,1788861600.0)
    assert len(frames)==3 and all(f.crc_ok for f in frames)
    export_frames(folder/'zigbee_reference.pcap',frames)
    export_frames(folder/'zigbee_reference.json',frames,{'source':'Synthetic half-sine O-QPSK; 18 kHz CFO; seed 802154'})
    print('Reference generated: 3 CRC-valid Off / On / Toggle frames')


if __name__=='__main__':main()
