"""The manual-dispatch ordering contract -- the hardest 20% of the binding.

These tests pin the exact call sequence Valve requires of a manual-dispatch
loop. Getting this order wrong does not crash loudly; it leaks callback
slots or corrupts payloads, and has broken mature bindings in the field
(see Steamworks.NET issue #413). So every rule below is asserted against
the scripted FakeSteamLib rather than trusted to code review.

The rules, restated from _dispatch.py's docstring:

  * RunFrame(pipe) is called exactly once per frame, before any
    GetNextCallback.
  * FreeLastCallback is called once for every successful GetNextCallback --
    and ALWAYS, even when decoding the payload is impossible or raises.
  * Unknown ids and wrong-sized payloads are delivered as raw bytes (never
    a corrupt struct) and still freed.
  * Nothing runs after GetNextCallback first returns false.
"""

import ctypes

import pytest

import pysteamnet
from pysteamnet import _dispatch
from pysteamnet._structs import LobbyCreated_t
from tests.fakes.fake_steam_lib import FakeSteamLib

PIPE = 7  # an arbitrary HSteamPipe; the fake only echoes it back


def _names(call_log):
    """The ordered method names from a fake's call_log -- order is the test."""
    return [entry[0] for entry in call_log]


# A small valid LobbyCreated_t (id 513) and its exact bytes, reused below.
def _lobby_created_bytes(result=1, lobby_id=0xABCD):
    s = LobbyCreated_t()
    s.m_eResult = result
    s.m_ulSteamIDLobby = lobby_id
    return bytes(s)


# ---------------------------------------------------------------------------
# a. RunFrame is called exactly once, and before any GetNextCallback.
# ---------------------------------------------------------------------------

def test_runframe_called_once_and_first():
    fake = FakeSteamLib([
        ("callback", 504, _lobby_created_bytes()),  # any plain callback
        ("callback", 505, b"\x00" * ctypes.sizeof(pysteamnet.LobbyDataUpdate_t)),
    ])

    _dispatch.run_frame(PIPE, lib=fake)

    names = _names(fake.call_log)
    assert names.count("RunFrame") == 1, "RunFrame must run exactly once per frame"
    assert names[0] == "RunFrame", "RunFrame must precede every GetNextCallback"
    # RunFrame must come before the first GetNextCallback specifically.
    assert names.index("RunFrame") < names.index("GetNextCallback")


# ---------------------------------------------------------------------------
# b. FreeLastCallback count == number of successful GetNextCallback returns.
# ---------------------------------------------------------------------------

def test_free_count_matches_successful_getnext():
    # Three plain callbacks -> three successful GetNextCallback returns,
    # plus a fourth GetNextCallback that returns false (no event behind it).
    payload_505 = b"\x00" * ctypes.sizeof(pysteamnet.LobbyDataUpdate_t)
    fake = FakeSteamLib([
        ("callback", 505, payload_505),
        ("callback", 505, payload_505),
        ("callback", 505, payload_505),
    ])

    delivered = _dispatch.run_frame(PIPE, lib=fake)
    names = _names(fake.call_log)

    assert len(delivered) == 3
    assert names.count("FreeLastCallback") == 3, "one free per successful GetNext"
    # Four GetNextCallback calls total: three that delivered, one that ended.
    assert names.count("GetNextCallback") == 4


# ---------------------------------------------------------------------------
# c. free-on-unknown: an unregistered id is delivered as raw bytes and freed.
# ---------------------------------------------------------------------------

def test_unknown_id_delivered_raw_and_freed():
    junk = b"\xde\xad\xbe\xef"
    fake = FakeSteamLib([("callback", 999999, junk)])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    assert len(delivered) == 1
    cb_id, payload = delivered[0]
    assert cb_id == 999999
    assert payload == junk, "unknown ids must come back as raw bytes, untouched"
    assert isinstance(payload, bytes)
    assert _names(fake.call_log).count("FreeLastCallback") == 1


# ---------------------------------------------------------------------------
# d. free-on-decode-surprise: a KNOWN id with the WRONG size is raw, not a
#    corrupt struct -- and still freed.
# ---------------------------------------------------------------------------

def test_known_id_wrong_size_delivered_raw_and_freed():
    # 513 is LobbyCreated_t, but we hand over too few bytes. Decoding into
    # the struct would read past the buffer / mis-map fields; the pump must
    # refuse and return the raw bytes instead.
    wrong_size = b"\x01\x02\x03"  # not sizeof(LobbyCreated_t)
    assert len(wrong_size) != ctypes.sizeof(LobbyCreated_t)
    fake = FakeSteamLib([("callback", 513, wrong_size)])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    assert len(delivered) == 1
    cb_id, payload = delivered[0]
    assert cb_id == 513
    assert payload == wrong_size, "size mismatch must fall back to raw bytes"
    assert isinstance(payload, bytes)
    assert _names(fake.call_log).count("FreeLastCallback") == 1


# ---------------------------------------------------------------------------
# e. Nothing follows the final failed GetNextCallback.
# ---------------------------------------------------------------------------

def test_nothing_after_final_failed_getnext():
    fake = FakeSteamLib([
        ("callback", 505, b"\x00" * ctypes.sizeof(pysteamnet.LobbyDataUpdate_t)),
    ])

    _dispatch.run_frame(PIPE, lib=fake)
    names = _names(fake.call_log)

    # The last GetNextCallback is the one that returned false (it ran after
    # the single event's free). Nothing -- no free, no anything -- may
    # follow it.
    last_getnext = len(names) - 1 - names[::-1].index("GetNextCallback")
    assert last_getnext == len(names) - 1, "GetNextCallback(false) must be the last call"


# ---------------------------------------------------------------------------
# f. An empty script: RunFrame once, GetNextCallback once, no frees, [].
# ---------------------------------------------------------------------------

def test_empty_frame():
    fake = FakeSteamLib([])

    delivered = _dispatch.run_frame(PIPE, lib=fake)
    names = _names(fake.call_log)

    assert delivered == []
    assert names.count("RunFrame") == 1
    assert names.count("GetNextCallback") == 1
    assert names.count("FreeLastCallback") == 0
    # And the exact order: RunFrame, then the single (false) GetNextCallback.
    assert names == ["RunFrame", "GetNextCallback"]


# ---------------------------------------------------------------------------
# g. A known id at the correct size decodes into the right struct + fields.
# ---------------------------------------------------------------------------

def test_known_id_correct_size_decodes_struct():
    payload_bytes = _lobby_created_bytes(result=1, lobby_id=0x1100AA55BB)
    fake = FakeSteamLib([("callback", 513, payload_bytes)])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    assert len(delivered) == 1
    cb_id, payload = delivered[0]
    assert cb_id == 513
    assert isinstance(payload, LobbyCreated_t), "correct-size known id -> the struct"
    assert payload.m_eResult == 1
    assert payload.m_ulSteamIDLobby == 0x1100AA55BB
    assert _names(fake.call_log).count("FreeLastCallback") == 1


# ---------------------------------------------------------------------------
# h. THE key test: if decoding raises, the exception propagates AND
#    FreeLastCallback still ran (the finally that protects the pipe).
# ---------------------------------------------------------------------------

def test_decode_exception_still_frees():
    sentinel = RuntimeError("boom from _decode")

    def exploding_decode(*args, **kwargs):
        raise sentinel

    original_decode = _dispatch._decode
    _dispatch._decode = exploding_decode
    try:
        fake = FakeSteamLib([
            ("callback", 505, b"\x00" * ctypes.sizeof(pysteamnet.LobbyDataUpdate_t)),
        ])
        with pytest.raises(RuntimeError) as caught:
            _dispatch.run_frame(PIPE, lib=fake)
        assert caught.value is sentinel, "the real exception must propagate, not be swallowed"
        # Even though decoding blew up, the finally must have freed the slot.
        assert _names(fake.call_log).count("FreeLastCallback") == 1
        # And the free came AFTER the GetNextCallback that delivered the event.
        names = _names(fake.call_log)
        assert names.index("FreeLastCallback") > names.index("GetNextCallback")
    finally:
        _dispatch._decode = original_decode
