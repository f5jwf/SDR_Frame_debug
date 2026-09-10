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


def load():
    try:
        obj=json.loads((PROFILE/'settings.json').read_text(encoding='utf8'))
        # Migrate the original default which erased a CW at the center frequency.
        if 'spectrum_mode' not in obj: obj['dc']=False
        allowed={f.name for f in fields(Settings)}
        return Settings(**{k:v for k,v in obj.items() if k in allowed})
    except (OSError,ValueError,TypeError): return Settings()


def save(settings):
    PROFILE.mkdir(parents=True,exist_ok=True)
    temp=PROFILE/'settings.tmp'
    temp.write_text(json.dumps(settings.public(),indent=2),encoding='utf8'); temp.replace(PROFILE/'settings.json')
