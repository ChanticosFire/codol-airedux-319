"""Conservative candidate for the observed LE32 frame envelope.

Only the transport envelope is parsed. Payload message shapes remain unknown.
No received frame is interpreted as an authenticated game message.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_FRAME_BODY = 1024 * 1024


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    body: bytes
    raw: bytes


class FrameParser:
    def __init__(self, max_body: int = MAX_FRAME_BODY):
        if not 1 <= max_body <= MAX_FRAME_BODY:
            raise ValueError("invalid frame limit")
        self.max_body = max_body
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        if not isinstance(data, bytes):
            raise TypeError("frame input must be bytes")
        self._buffer.extend(data)
        result = []
        while len(self._buffer) >= 4:
            size = int.from_bytes(self._buffer[:4], "little")
            if size == 0 or size > self.max_body:
                self._buffer.clear()
                raise FrameError(f"invalid frame size {size}")
            total = 4 + size
            if len(self._buffer) < total:
                break
            raw = bytes(self._buffer[:total])
            result.append(Frame(body=raw[4:], raw=raw))
            del self._buffer[:total]
        if len(self._buffer) > 4 + self.max_body:
            self._buffer.clear()
            raise FrameError("buffer limit exceeded")
        return result

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def finish(self) -> None:
        if self._buffer:
            raise FrameError(f"truncated frame ({len(self._buffer)} buffered bytes)")
