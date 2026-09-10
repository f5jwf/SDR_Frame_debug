"""Registry can be extended via the sdr_debug.protocols entry-point group."""
from importlib.metadata import entry_points
from .zigbee.plugin import ZigbeePlugin
from .ism.plugin import ISM433Plugin,ISM868Plugin


def available():
    plugins={p.id:p for p in (ZigbeePlugin,ISM433Plugin,ISM868Plugin)}
    for ep in entry_points(group='sdr_debug.protocols'):
        plugins[ep.name]=ep.load()
    return plugins
