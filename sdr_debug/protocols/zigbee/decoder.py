"""Bounds-checked MAC (2003/2006), Zigbee NWK/APS and common ZCL fields."""
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.exceptions import InvalidTag


class Reader:
    def __init__(self, data): self.data, self.pos = data, 0
    def take(self, n):
        if self.pos+n > len(self.data): raise ValueError('Trame tronquée')
        out = self.data[self.pos:self.pos+n]; self.pos += n
        return out
    def u8(self): return int.from_bytes(self.take(1), 'little')
    def u16(self): return int.from_bytes(self.take(2), 'little')
    def rest(self): return self.take(len(self.data)-self.pos)


def secure_payload(data, offset, key, source=None):
    r = Reader(data); r.pos = offset
    control = r.u8(); counter = r.take(4)
    if control & 32: source = r.take(8)
    key_id = (control >> 3) & 3
    seq = r.u8() if key_id == 1 else None
    info = {'control': f'0x{control:02x}', 'counter': int.from_bytes(counter, 'little'),
            'key_id': key_id, 'key_sequence': seq, 'status': 'Chiffré — clé absente'}
    if source: info['source_ieee'] = source[::-1].hex()
    if key is None: return None, info
    if source is None:
        info['status'] = 'Chiffré — adresse IEEE du nonce absente'; return None, info
    if key_id not in (0, 1):
        info['status'] = 'Dérivation de clé transport/load non prise en charge'; return None, info
    # Zigbee transmits security level zero but uses ENC-MIC32 (level 5).
    level = (control & 7) or 5
    if level not in (5, 6, 7):
        info['status'] = 'Mode CCM* non pris en charge'; return None, info
    effective = (control & 0xf8) | level
    aad = bytearray(data[:r.pos]); aad[offset] = effective
    nonce = source + counter + bytes([effective])
    try:
        plain = AESCCM(key, tag_length={5:4, 6:8, 7:16}[level]).decrypt(nonce, data[r.pos:], bytes(aad))
    except InvalidTag:
        info['status'] = 'Échec authentification MIC — clé incorrecte ou trame altérée'
        return None, info
    info['status'] = 'Déchiffré — MIC vérifié'
    return plain, info


CLUSTERS = {0:'Basic', 3:'Identify', 6:'On/Off', 8:'Level Control', 0x402:'Temperature', 0x405:'Humidity'}
ZCL_COMMANDS = {0:'Read Attributes', 1:'Read Attributes Response', 2:'Write Attributes',
                4:'Write Attributes Response', 6:'Configure Reporting', 10:'Report Attributes', 11:'Default Response'}


def zcl_decode(data, cluster):
    r=Reader(data); fc=r.u8()
    out={'frame_control':f'0x{fc:02x}', 'direction':(fc>>3)&1, 'manufacturer_specific':bool(fc&4)}
    if fc&4: out['manufacturer_code']=f'0x{r.u16():04x}'
    out['transaction_sequence']=r.u8(); command=r.u8(); out['command']=f'0x{command:02x}'
    out['command_name']=ZCL_COMMANDS.get(command, 'Unknown') if fc&3 == 0 else ({0:'Off',1:'On',2:'Toggle'}.get(command,'Cluster command') if cluster == 6 else 'Cluster command')
    if fc&3 == 0 and command == 0:
        out['attributes']=[f'0x{r.u16():04x}' for _ in range((len(data)-r.pos)//2)]
    elif fc&3 == 0 and command in (1, 2, 10):
        attrs=[]
        while r.pos<len(data):
            attr={'id':f'0x{r.u16():04x}'}; attrs.append(attr)
            if command==1:
                attr['status']=r.u8()
                if attr['status']: continue
            typ=r.u8(); attr['type']=f'0x{typ:02x}'
            if 0x20<=typ<=0x27: attr['value']=int.from_bytes(r.take(typ-0x20+1),'little')
            elif 0x28<=typ<=0x2f: attr['value']=int.from_bytes(r.take(typ-0x28+1),'little',signed=True)
            elif typ in (0x10,0x18,0x30): attr['value']=r.u8()
            elif typ in (0x19,0x31): attr['value']=r.u16()
            elif typ in (0x41,0x42):
                n=r.u8(); raw=r.take(n) if n!=255 else b''
                attr['value']=raw.decode('utf8',errors='replace') if typ==0x42 else raw.hex()
            else:
                attr['undecoded']=r.rest().hex(); break
        out['attributes']=attrs
    out['payload']=r.rest().hex()
    return out


def decode(raw, network_key=None, link_key=None):
    tree={}
    try:
        if len(raw)<5: raise ValueError('PSDU trop courte')
        r=Reader(raw[:-2]); fc=r.u16(); version=(fc>>12)&3; typ=fc&7
        mac={'frame_control':f'0x{fc:04x}', 'type':{0:'Beacon',1:'Data',2:'ACK',3:'Command'}.get(typ,str(typ)),
             'security':bool(fc&8), 'version':version, 'pan_compression':bool(fc&64)}
        tree['MAC']=mac
        if version>=2:
            mac['status']='MAC 2015/2020 non pris en charge'; mac['payload']=r.rest().hex(); return tree
        mac['sequence']=r.u8()
        dest=(fc>>10)&3; src=(fc>>14)&3
        if dest==1 or src==1: raise ValueError('Mode adresse réservé')
        if dest:
            mac['pan']=f'0x{r.u16():04x}'; mac['destination']=r.take(2 if dest==2 else 8)[::-1].hex()
        if src:
            mac['source_pan']=mac.get('pan') if fc&64 and dest else f'0x{r.u16():04x}'
            mac['source']=r.take(2 if src==2 else 8)[::-1].hex()
        payload=r.rest(); mac['payload']=payload.hex()
        if fc&8:
            mac['status']='Sécurité MAC — décodage arrêté'; return tree
        if typ!=1 or not payload: return tree
        n=Reader(payload); nf=n.u16()
        nwk={'frame_control':f'0x{nf:04x}', 'type':nf&3, 'version':(nf>>2)&15,
             'route_discovery':(nf>>6)&3, 'destination':f'{n.u16():04x}', 'source':f'{n.u16():04x}',
             'radius':n.u8(), 'sequence':n.u8(), 'security':bool(nf&0x200)}
        tree['NWK']=nwk
        if nwk['version']!=2:
            nwk['status']='Version NWK inconnue'; nwk['payload']=n.rest().hex(); return tree
        source=None
        if nf&0x800: nwk['destination_ieee']=n.take(8)[::-1].hex()
        if nf&0x1000: source=n.take(8); nwk['source_ieee']=source[::-1].hex()
        if nf&0x100: nwk['multicast_control']=n.u8()
        if nf&0x400:
            count=n.u8(); nwk['relay_index']=n.u8(); nwk['relays']=[f'{n.u16():04x}' for _ in range(count)]
        if nf&0x200:
            aps, sec=secure_payload(payload,n.pos,network_key,source); nwk['security_details']=sec
            if aps is None: return tree
            if sec.get('source_ieee'): source=bytes.fromhex(sec['source_ieee'])[::-1]
        else: aps=n.rest()
        if nf&3:
            nwk['command_payload']=aps.hex(); return tree
        a=Reader(aps); af=a.u8(); delivery=(af>>2)&3
        at={'frame_control':f'0x{af:02x}', 'type':af&3, 'delivery_mode':delivery,'security':bool(af&32)}; tree['APS']=at
        if af&3 not in (0,2): at['payload']=a.rest().hex(); return tree
        if af&3==2 and af&16:
            at['counter']=a.u8(); at['payload']=a.rest().hex(); return tree
        if delivery==3: at['group']=f'0x{a.u16():04x}'
        else: at['destination_endpoint']=a.u8()
        cluster=a.u16(); at['cluster']=f'0x{cluster:04x}'; at['cluster_name']=CLUSTERS.get(cluster,'Unknown')
        at['profile']=f'0x{a.u16():04x}'; at['source_endpoint']=a.u8(); at['counter']=a.u8()
        if af&128:
            ext=a.u8(); at['extended_header']=ext
            if ext&3:
                at['block_number']=a.u8(); at['status']='Fragment APS — réassemblage non pris en charge'
                at['payload']=a.rest().hex(); return tree
        if af&32:
            zcl,sec=secure_payload(aps,a.pos,link_key,source); at['security_details']=sec
            if zcl is None: return tree
        else: zcl=a.rest()
        if af&3==0 and at['profile']!='0x0000' and zcl: tree['ZCL']=zcl_decode(zcl,cluster)
        else: at['payload']=zcl.hex()
    except (ValueError, IndexError) as exc:
        tree['Erreur']=str(exc)
    return tree
