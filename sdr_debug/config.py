import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from dataclasses import fields
from .sdr.backends import Settings

PROFILE=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.config'))/'SDRFrameDebug'


def setup_logs():
    PROFILE.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(PROFILE/'application.log',maxBytes=2_000_000,backupCount=3,encoding='utf8')
    logging.basicConfig(level=logging.INFO,handlers=[handler],format='%(asctime)s %(levelname)s %(name)s %(message)s')


BANDS=('zigbee','ism433','ism868')


def defaults(band):
    if band=='zigbee':return Settings()
    frequency=433920000 if band=='ism433' else 868300000
    return Settings(workspace=band,protocol=band,center=frequency,rx_frequency=frequency,
                    sample_rate=1000000,span=1000000,channel=1)


def settings_path(band):
    if band not in BANDS:raise ValueError('Unknown workspace')
    return PROFILE/('settings.json' if band=='zigbee' else f'settings_{band}.json')


def load(band='zigbee'):
    try:
        obj=json.loads(settings_path(band).read_text(encoding='utf8'))
        # Migrate the original default which erased a CW at the center frequency.
        if 'spectrum_mode' not in obj: obj['dc']=False
        allowed={f.name for f in fields(Settings)}
        values=defaults(band).public();values.update({k:v for k,v in obj.items() if k in allowed});values['workspace']=band
        if band!='zigbee':values['protocol']=band
        return Settings(**values)
    except (OSError,ValueError,TypeError): return defaults(band)


def save(settings):
    PROFILE.mkdir(parents=True,exist_ok=True)
    path=settings_path(settings.workspace);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(settings.public(),indent=2),encoding='utf8'); temp.replace(path)
