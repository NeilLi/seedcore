import struct
import zlib

import pytest

from seedcore.robotics.fast_spine.protocol import (
    FrameDecoder,
    MAX_ENCODED,
    MAX_PAYLOAD,
    MessageType,
    cobs_decode,
    cobs_encode,
    decode_frame,
    encode_frame,
)

KEY = b"k" * 32


@pytest.mark.parametrize(
    "data", [b"", b"\0", b"abc\0def", bytes(range(256)), b"a" * 1024]
)
def test_cobs_and_authenticated_frame_roundtrip(data):
    assert cobs_decode(cobs_encode(data)) == data
    payload = {"data": data.hex()}
    frame = encode_frame(MessageType.HELLO, 0, payload, KEY)
    assert decode_frame(frame, KEY) == (MessageType.HELLO, 0, payload)
    decoder = FrameDecoder(KEY)
    result = []
    for byte in frame:
        result.extend(decoder.feed(bytes([byte])))
    assert result == [(MessageType.HELLO, 0, payload)]


def test_stream_recovers_after_corruption_and_oversize():
    frame = encode_frame(MessageType.HELLO, 0, {"profile": "simulation_only"}, KEY)
    corrupted = bytearray(frame)
    corrupted[8] ^= 1
    decoder = FrameDecoder(KEY)
    assert decoder.feed(bytes(corrupted)) == []
    assert decoder.feed(b"x" * (MAX_ENCODED + 100) + b"\0" + frame) == [
        (MessageType.HELLO, 0, {"profile": "simulation_only"})
    ]
    assert decoder.errors >= 2
    assert len(decoder._buffer) == 0


def test_crc_is_not_authentication_and_header_is_authenticated():
    frame = encode_frame(MessageType.HEARTBEAT, 1, {"session_id": "demo"}, KEY)
    body = bytearray(cobs_decode(frame[:-1]))
    body[4] = 2  # change sequence and recompute the non-secret CRC
    body[-4:] = struct.pack("<I", zlib.crc32(body[:-4]))
    with pytest.raises(ValueError, match="authentication"):
        decode_frame(cobs_encode(body) + b"\0", KEY)


def test_missing_key_unsupported_version_and_oversized_payload_rejected():
    with pytest.raises(ValueError):
        encode_frame(MessageType.HELLO, 0, {}, b"short")
    with pytest.raises(ValueError):
        encode_frame(MessageType.HELLO, 0, {"data": "a" * MAX_PAYLOAD}, KEY)
    frame = encode_frame(MessageType.HELLO, 0, {}, KEY)
    body = bytearray(cobs_decode(frame[:-1]))
    body[2] = 2
    body[-4:] = struct.pack("<I", zlib.crc32(body[:-4]))
    with pytest.raises(ValueError, match="header/version"):
        decode_frame(cobs_encode(body) + b"\0", KEY)
