"""Wire v1: COBS + bounded LE header + JSON + HMAC-SHA256 + CRC32/IEEE.

Authentication is mandatory, including control/heartbeat frames. A browser does
not receive this channel key. Keys are explicitly supplied by an enrolled host.
"""

from __future__ import annotations

from enum import IntEnum
import hmac
import json
import struct
import zlib

from .contracts import MAX_PAYLOAD, MAX_SEQUENCE, canonical

HEADER = struct.Struct("<2sBBIH")  # magic, version, message type, seq, payload length
DOMAIN = b"seedcore.fast-spine.wire.v1\x00"
MAX_DECODED = HEADER.size + MAX_PAYLOAD + 32 + 4
MAX_ENCODED = MAX_DECODED + MAX_DECODED // 254 + 2


class MessageType(IntEnum):
    HELLO = 1
    SESSION_OPEN = 2
    CHUNK = 3
    HEARTBEAT = 4
    CANCEL = 5
    REVOKE = 6
    STATE = 7
    SESSION_END = 8


def cobs_encode(data: bytes) -> bytes:
    result = bytearray(b"\x00")
    index, code = 0, 1
    for byte in data:
        if byte == 0:
            result[index] = code
            index, code = len(result), 1
            result.append(0)
        else:
            result.append(byte)
            code += 1
            if code == 255:
                result[index] = code
                index, code = len(result), 1
                result.append(0)
    result[index] = code
    return bytes(result)


def cobs_decode(data: bytes) -> bytes:
    if not data or len(data) >= MAX_ENCODED or 0 in data:
        raise ValueError("invalid/oversized COBS frame")
    result = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        i += 1
        end = i + code - 1
        if end > len(data):
            raise ValueError("truncated COBS frame")
        result.extend(data[i:end])
        i = end
        if code < 255 and i < len(data):
            result.append(0)
    if len(result) > MAX_DECODED:
        raise ValueError("decoded frame too large")
    return bytes(result)


def _key(key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("a provisioned 32-byte channel key is required")
    return key


def encode_frame(
    message_type: MessageType, sequence: int, payload: dict, key: bytes
) -> bytes:
    key = _key(key)
    kind = MessageType(message_type)
    if type(sequence) is not int or not 0 <= sequence <= MAX_SEQUENCE:
        raise ValueError("invalid frame sequence")
    data = canonical(payload)
    if not isinstance(payload, dict) or len(data) > MAX_PAYLOAD:
        raise ValueError("invalid/oversized payload")
    header = HEADER.pack(b"SC", 1, int(kind), sequence, len(data))
    body = header + data
    body += hmac.digest(key, DOMAIN + body, "sha256")
    body += struct.pack("<I", zlib.crc32(body))
    return cobs_encode(body) + b"\x00"


def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON field")
        result[name] = value
    return result


def decode_frame(frame: bytes, key: bytes):
    key = _key(key)
    if not frame.endswith(b"\x00") or len(frame) > MAX_ENCODED:
        raise ValueError("invalid frame boundary/size")
    body = cobs_decode(frame[:-1])
    if len(body) < HEADER.size + 36:
        raise ValueError("truncated frame")
    if zlib.crc32(body[:-4]) != struct.unpack("<I", body[-4:])[0]:
        raise ValueError("CRC mismatch")
    magic, version, kind, sequence, length = HEADER.unpack(body[: HEADER.size])
    if (
        magic != b"SC"
        or version != 1
        or length > MAX_PAYLOAD
        or len(body) != HEADER.size + length + 36
    ):
        raise ValueError("invalid header/version/length")
    kind = MessageType(kind)
    content, tag = body[: HEADER.size + length], body[-36:-4]
    if not hmac.compare_digest(tag, hmac.digest(key, DOMAIN + content, "sha256")):
        raise ValueError("frame authentication failed")
    payload_bytes = content[HEADER.size :]
    payload = json.loads(
        payload_bytes,
        object_pairs_hook=_unique_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if not isinstance(payload, dict) or canonical(payload) != payload_bytes:
        raise ValueError("non-canonical payload")
    return kind, sequence, payload


class FrameDecoder:
    """Bounded incremental decoder; oversized frames discarded until delimiter."""

    def __init__(self, key: bytes):
        self._key = _key(key)
        self._buffer = bytearray()
        self._discarding = False
        self.errors = 0

    def feed(self, incoming: bytes):
        frames = []
        for byte in incoming:
            if byte == 0:
                if self._buffer and not self._discarding:
                    try:
                        frames.append(
                            decode_frame(bytes(self._buffer) + b"\x00", self._key)
                        )
                    except (ValueError, UnicodeError, RecursionError):
                        self.errors += 1
                self._buffer.clear()
                self._discarding = False
            elif not self._discarding:
                self._buffer.append(byte)
                if len(self._buffer) >= MAX_ENCODED:
                    self.errors += 1
                    self._buffer.clear()
                    self._discarding = True
        return frames
