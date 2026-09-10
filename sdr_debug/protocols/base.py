from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Frame:
    timestamp: float
    channel: int
    frequency: float
    raw: bytes
    crc_ok: bool | None
    level: float
    fields: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    favorite: bool = False
    protocol: str = "zigbee"


class ProtocolPlugin(Protocol):
    id: str
    name: str
    channels: dict[int, float]
    bandwidth: float
    min_sample_rate: float

    def configure(self, sample_rate, center_frequency, channel_frequency, options): ...
    def process_iq(self, iq_block, timestamp) -> list[Frame]: ...
    def decode(self, frame) -> dict: ...
    def format_summary(self, frame) -> str: ...
    def get_filters(self) -> list[str]: ...
