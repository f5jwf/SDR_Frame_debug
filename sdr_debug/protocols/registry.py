"""Registry can be extended via the sdr_debug.protocols entry-point group."""
from importlib.metadata import entry_points
from .zigbee.plugin import ZigbeePlugin


def available():
    plugins={ZigbeePlugin.id:ZigbeePlugin}
    for ep in entry_points(group='sdr_debug.protocols'):
        plugins[ep.name]=ep.load()
    return plugins
