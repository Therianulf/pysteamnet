"""Layout assertions for every ctypes struct this binding touches.

Pure Python -- no Steam client, no SDK, no markers. This is the test
that catches the silent-corruption class of bug described at the top of
``pysteamnet._structs``: a wrong ``_pack_`` or a misordered field does
not crash, it quietly reads the wrong bytes. So we pin down sizes and a
handful of distinguishing field offsets, and we do it for BOTH of
Valve's platform packings (pack(4) on the POSIX family, pack(8) on
Windows) regardless of which platform happens to run the test.

The golden numbers below were live-verified against the real Steam
client on macOS arm64 (SDK v1.64). ``pack8`` is what a Windows build of
the same SDK lays out; we reproduce it here by rebuilding each struct
under ``_pack_ = 8`` so the Windows layout is covered from any host.
"""

import ctypes
import struct

import pytest

from pysteamnet import _structs as st
from pysteamnet._structs import PACK_VALVE_CALLBACK


# ---------------------------------------------------------------------------
# The golden table. Each row: the struct class, its size under Valve's
# pack(4) (POSIX) and pack(8) (Windows). These are the classes that carry
# the platform-dependent VALVE_CALLBACK_PACK pragma, so their size differs
# between the two packings -- which is exactly what we want to pin.
# ---------------------------------------------------------------------------

#: class -> (size under pack(4), size under pack(8))
VALVE_PACKED_GOLDEN = {
    st.CallbackMsg_t:            (20, 24),
    st.SteamAPICallCompleted_t:  (16, 16),
    st.LobbyInvite_t:            (24, 24),
    st.LobbyEnter_t:             (20, 24),
    st.LobbyDataUpdate_t:        (20, 24),
    st.LobbyChatUpdate_t:        (28, 32),
    st.LobbyChatMsg_t:           (24, 24),
    st.LobbyMatchList_t:         (4, 4),
    st.LobbyCreated_t:           (12, 16),
    st.PersonaStateChange_t:     (12, 16),
    st.GameLobbyJoinRequested_t: (16, 16),
}

#: The "current platform" index into the (pack4, pack8) tuples above:
#: 0 when this host packs at 4 (POSIX), 1 when it packs at 8 (Windows).
#: Driven entirely by the package's own PACK_VALVE_CALLBACK so the test
#: and the code can never disagree about which platform they're on.
_PLATFORM_INDEX = 0 if PACK_VALVE_CALLBACK == 4 else 1

#: Structs whose size is an absolute constant on every platform: the
#: pack(1) networking value/callback types, the naturally-aligned
#: message struct, and SteamNetConnectionInfo_t (which the header
#: defines under the platform pack(4)/pack(8) region at
#: steamnetworkingtypes.h:673, but whose explicit padding makes its
#: layout identical under pack 1/4/8 -- 696 bytes everywhere). We never
#: rebuild these under another packing. SteamNetworkingMessage_t is 216
#: bytes on any 64-bit build (it embeds pointers and the 136-byte
#: identity).
FIXED_SIZE_GOLDEN = {
    st.SteamNetworkingIdentity:                  136,
    st.SteamNetConnectionInfo_t:                 696,
    st.SteamNetworkingMessagesSessionRequest_t:  136,
    st.SteamNetworkingMessagesSessionFailed_t:   696,
    st.SteamNetworkingMessage_t:                 216,
}


def _rebuild_under_pack(cls, pack):
    """Return a fresh Structure with cls's fields laid out under `pack`.

    Lets us measure the Windows (pack 8) layout of a callback struct from
    a POSIX host, and vice versa, without touching the real class.
    """
    return type(
        f"{cls.__name__}__pack{pack}",
        (ctypes.Structure,),
        {"_pack_": pack, "_fields_": list(cls._fields_)},
    )


# ---------------------------------------------------------------------------
# Sizes -- current platform.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", list(VALVE_PACKED_GOLDEN), ids=lambda c: c.__name__)
def test_valve_struct_size_on_this_platform(cls):
    """Each Valve-packed struct has the golden size for THIS host's packing."""
    expected = VALVE_PACKED_GOLDEN[cls][_PLATFORM_INDEX]
    assert ctypes.sizeof(cls) == expected, (
        f"{cls.__name__}: sizeof={ctypes.sizeof(cls)} but golden for "
        f"pack({PACK_VALVE_CALLBACK}) is {expected}"
    )


# ---------------------------------------------------------------------------
# Sizes -- BOTH packings, rebuilt from the field list.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", list(VALVE_PACKED_GOLDEN), ids=lambda c: c.__name__)
def test_valve_struct_size_under_both_packings(cls):
    """Rebuilt under pack(4) AND pack(8), sizes match the golden pair.

    This is the cross-platform guarantee: a macOS/Linux dev and a Windows
    player get the same field at the same offset, because both layouts are
    pinned here from one host.
    """
    pack4_golden, pack8_golden = VALVE_PACKED_GOLDEN[cls]

    pack4 = _rebuild_under_pack(cls, 4)
    pack8 = _rebuild_under_pack(cls, 8)

    assert ctypes.sizeof(pack4) == pack4_golden, (
        f"{cls.__name__} under pack(4): {ctypes.sizeof(pack4)} != {pack4_golden}"
    )
    assert ctypes.sizeof(pack8) == pack8_golden, (
        f"{cls.__name__} under pack(8): {ctypes.sizeof(pack8)} != {pack8_golden}"
    )


# ---------------------------------------------------------------------------
# Sizes -- the fixed-packing structs (pack(1) / natural). Absolute, same
# on every platform; we do NOT rebuild these.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", list(FIXED_SIZE_GOLDEN), ids=lambda c: c.__name__)
def test_fixed_packing_struct_size(cls):
    """pack(1) / naturally-aligned structs have their one absolute size."""
    expected = FIXED_SIZE_GOLDEN[cls]
    assert ctypes.sizeof(cls) == expected, (
        f"{cls.__name__}: sizeof={ctypes.sizeof(cls)} != {expected}"
    )


# ---------------------------------------------------------------------------
# The packing sentinel. steamclientpublic.h defines ValvePackingSentinel_t
# and compile-time-asserts that it is 24 bytes under the small (pack 4)
# packing and 32 bytes under the large (pack 8) packing. That single struct
# is how Valve proves the build's packing matches the SDK's expectation;
# we reproduce the same proof in ctypes.
# ---------------------------------------------------------------------------

def test_valve_packing_sentinel():
    """{uint32,uint64,uint16,double} == 24 bytes at pack4, 32 at pack8."""
    sentinel_fields = [
        ("m_32bit", ctypes.c_uint32),
        ("m_64bit", ctypes.c_uint64),
        ("m_16bit", ctypes.c_uint16),
        ("m_double", ctypes.c_double),
    ]

    sentinel4 = type("ValvePackingSentinel4", (ctypes.Structure,),
                     {"_pack_": 4, "_fields_": sentinel_fields})
    sentinel8 = type("ValvePackingSentinel8", (ctypes.Structure,),
                     {"_pack_": 8, "_fields_": sentinel_fields})

    assert ctypes.sizeof(sentinel4) == 24
    assert ctypes.sizeof(sentinel8) == 32


# ---------------------------------------------------------------------------
# Distinguishing offsets. Size alone can coincide; these offsets are where
# the two packings actually diverge (or pointedly do NOT), so they catch a
# struct that happens to size-match for the wrong reason.
# ---------------------------------------------------------------------------

def _offset(cls, field_name):
    """Byte offset of a named field within a ctypes Structure."""
    return getattr(cls, field_name).offset


def test_offsets_that_distinguish_the_packings():
    """Spot-check the fields whose offset is the tell between pack4/pack8."""
    enter4 = _rebuild_under_pack(st.LobbyEnter_t, 4)
    enter8 = _rebuild_under_pack(st.LobbyEnter_t, 8)
    # m_bLocked sits right after uint64 + uint32 == 12 bytes in BOTH
    # packings (a uint32 never needs more than 4-byte alignment), so this
    # offset is a deliberate "stays put" check.
    assert _offset(enter4, "m_bLocked") == 12
    assert _offset(enter8, "m_bLocked") == 12

    created4 = _rebuild_under_pack(st.LobbyCreated_t, 4)
    created8 = _rebuild_under_pack(st.LobbyCreated_t, 8)
    # m_eResult is an int32; the uint64 that follows aligns to min(pack,8).
    # Under pack(4) the uint64 starts at offset 4; under pack(8) it gets
    # padded out to offset 8. This is the canonical packing divergence.
    assert _offset(created4, "m_ulSteamIDLobby") == 4
    assert _offset(created8, "m_ulSteamIDLobby") == 8

    msg4 = _rebuild_under_pack(st.CallbackMsg_t, 4)
    msg8 = _rebuild_under_pack(st.CallbackMsg_t, 8)
    # Two int32s then a pointer; the pointer aligns to min(pack, 8) == 8
    # on a 64-bit build either way, so m_pubParam lands at offset 8 in
    # both. (This is why CallbackMsg_t is 20 vs 24: the trailing int32
    # gets tail-padded under pack(8), not the pointer.)
    assert _offset(msg4, "m_pubParam") == 8
    assert _offset(msg8, "m_pubParam") == 8


# ---------------------------------------------------------------------------
# SteamNetworkingIdentity internals -- pack(1), same everywhere. The union
# must begin at byte 8 (after two int32 header fields) and the SteamID64
# alias must write the low 8 bytes of that union.
# ---------------------------------------------------------------------------

def test_identity_field_offsets():
    """m_eType@0, m_cbSize@4, and the union (m_steamID64) starts at 8."""
    assert _offset(st.SteamNetworkingIdentity, "m_eType") == 0
    assert _offset(st.SteamNetworkingIdentity, "m_cbSize") == 4
    # m_steamID64 is reached through the anonymous union; its offset is the
    # union's offset, which must be 8 (two int32s, pack(1) leaves no gap).
    assert _offset(st.SteamNetworkingIdentity, "m_steamID64") == 8


def test_identity_steamid_writes_union_bytes():
    """Setting m_steamID64 lands in bytes [8:16] as a little-endian uint64.

    Exercises the anonymous-union access end to end: poke the alias, then
    read the raw bytes of the whole struct and confirm the id is sitting
    exactly where Valve's flat SetSteamID64 helper would put it.
    """
    ident = st.SteamNetworkingIdentity()
    value = 0x1122334455667788
    ident.m_steamID64 = value

    raw = bytes(ident)
    assert raw[8:16] == struct.pack("<Q", value)
