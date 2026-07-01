from dataclasses import dataclass
from typing import Literal

EventType = Literal[
    'message',
    'done',
    'error'
]

@dataclass
class StreamChunk:
    event: EventType
    data: str