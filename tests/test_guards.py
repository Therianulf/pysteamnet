"""Tests for the friendly preflight guards and the wrappers that use them.

Two layers are covered here:

  1. The helpers in pysteamnet._guards directly -- table-driven, so a new
     row is the cheapest possible regression test.
  2. A handful of real SteamAPI_* wrappers, to prove the guard fires
     BEFORE any foreign call. We assert "before FFI" by pointing the
     loader's cached library at a sentinel that explodes on ANY attribute
     access: if the guard let us through, ctypes would reach for
     lib.SteamAPI_... and we'd see the sentinel's AttributeError instead
     of the expected ValueError/TypeError. Seeing the right exception
     therefore proves no call crossed into C.

None of these tests need Steam, the SDK, or the real binary -- they are
pure Python and run in any environment.
"""

import enum

import pytest

import pysteamnet as steam
from pysteamnet import _guards, _loader
from pysteamnet._constants import ELobbyType


# ---------------------------------------------------------------------------
# A sentinel "library" that refuses every attribute access.
#
# The wrappers fetch the C function with get_lib().SteamAPI_... -- so if a
# guard ever lets a bad value through, the very next thing the wrapper does
# is touch an attribute on this object, which raises AttributeError. Any
# test that expects a guard to fire uses pytest.raises(ValueError/TypeError)
# and so would FAIL loudly (with AttributeError) if FFI were attempted.
# ---------------------------------------------------------------------------

class _ExplodingLib:
    """Stand-in for the loaded CDLL that proves no FFI happened."""

    def __getattr__(self, name):
        raise AttributeError(
            f"FFI was attempted ({name!r}) -- a guard should have stopped this first."
        )


@pytest.fixture
def no_ffi(monkeypatch):
    """Install the exploding library as the loader's cached handle.

    Restored automatically by monkeypatch after the test, so we never
    poison _loader._lib for other test files in the same pytest run.
    """
    monkeypatch.setattr(_loader, "_lib", _ExplodingLib())


# A tiny enum to exercise check_enum without depending on Valve's values.
class _Color(enum.IntEnum):
    RED = 1
    GREEN = 2
    BLUE = 3


# ===========================================================================
# check_bytes
# ===========================================================================

def test_check_bytes_rejects_str_with_encode_hint():
    with pytest.raises(TypeError) as excinfo:
        _guards.check_bytes("payload", "hello")
    msg = str(excinfo.value)
    assert "payload" in msg
    # The whole point of the message is to tell the caller how to fix it.
    assert "encode" in msg


@pytest.mark.parametrize("value", [b"hi", bytearray(b"hi"), memoryview(b"hi")])
def test_check_bytes_accepts_bytes_like(value):
    # No exception == pass. bytearray and memoryview are valid payloads too.
    _guards.check_bytes("payload", value)


def test_check_bytes_rejects_non_bytes_type():
    with pytest.raises(TypeError):
        _guards.check_bytes("payload", 123)


def test_check_bytes_max_len_enforced():
    with pytest.raises(ValueError) as excinfo:
        _guards.check_bytes("payload", b"toolong", max_len=3)
    assert "3" in str(excinfo.value)


def test_check_bytes_max_len_boundary_ok():
    # Exactly at the limit is allowed; only strictly-greater is rejected.
    _guards.check_bytes("payload", b"abc", max_len=3)


# ===========================================================================
# check_steamid
# ===========================================================================

@pytest.mark.parametrize("bad", [0, -1, -(2**63), 2**64, 2**64 + 5])
def test_check_steamid_rejects_out_of_range(bad):
    with pytest.raises((ValueError,)):
        _guards.check_steamid("steamID", bad)


def test_check_steamid_rejects_bool():
    # bool is a subclass of int; a True SteamID is a bug, not a 1.
    with pytest.raises(TypeError):
        _guards.check_steamid("steamID", True)


@pytest.mark.parametrize("good", [1, 76561197960265728, 2**64 - 1])
def test_check_steamid_accepts_valid(good):
    _guards.check_steamid("steamID", good)


def test_check_steamid_zero_message_is_helpful():
    # A zero SteamID is the classic "async result hasn't arrived" bug;
    # the message should point at that.
    with pytest.raises(ValueError) as excinfo:
        _guards.check_steamid("steamIDLobby", 0)
    assert "0" in str(excinfo.value)


# ===========================================================================
# check_enum
# ===========================================================================

def test_check_enum_rejects_invalid_int_names_enum_and_members():
    with pytest.raises(ValueError) as excinfo:
        _guards.check_enum("eColor", 99, _Color)
    msg = str(excinfo.value)
    assert "_Color" in msg            # names the enum
    assert "RED" in msg and "BLUE" in msg  # lists members so the fix is visible


def test_check_enum_accepts_member():
    _guards.check_enum("eColor", _Color.GREEN, _Color)


def test_check_enum_accepts_raw_int_value():
    # A plain int that happens to be a valid member value passes -- mirrors
    # how C code passes the bare integer.
    _guards.check_enum("eColor", 2, _Color)


def test_check_enum_rejects_bool():
    with pytest.raises(TypeError):
        _guards.check_enum("eColor", True, _Color)


def test_check_enum_rejects_non_int():
    with pytest.raises(TypeError):
        _guards.check_enum("eColor", "GREEN", _Color)


# ===========================================================================
# check_str
# ===========================================================================

def test_check_str_rejects_bytes_with_direction_hint():
    with pytest.raises(TypeError) as excinfo:
        _guards.check_str("pchKey", b"key")
    msg = str(excinfo.value)
    assert "pchKey" in msg
    # The fix here is the OPPOSITE direction from check_bytes: do NOT encode,
    # pysteamnet encodes for you. The message should say it's text.
    assert "str" in msg and "bytes" in msg


def test_check_str_accepts_str():
    _guards.check_str("pchKey", "key")


def test_check_str_max_len_counts_utf8_bytes():
    # "e" is 1 byte; the accented form below is 2 bytes in UTF-8, so two of
    # them are 4 bytes and must exceed a max_len of 3.
    two_byte_chars = "éé"  # two characters, four UTF-8 bytes
    with pytest.raises(ValueError):
        _guards.check_str("pchKey", two_byte_chars, max_len=3)


def test_check_str_max_len_ok_when_under_in_bytes():
    # Three ASCII chars are three bytes -- exactly at the limit, allowed.
    _guards.check_str("pchKey", "abc", max_len=3)


def test_check_str_rejects_non_str():
    with pytest.raises(TypeError):
        _guards.check_str("pchKey", 123)


# ===========================================================================
# check_flags
# ===========================================================================

def test_check_flags_rejects_stray_bit():
    # valid_bits allows only bit 0 and bit 1 (0b011); bit 2 is stray.
    with pytest.raises(ValueError) as excinfo:
        _guards.check_flags("flags", 0b100, valid_bits=0b011)
    assert "flags" in str(excinfo.value)


@pytest.mark.parametrize("value", [0, 0b001, 0b010, 0b011])
def test_check_flags_accepts_subsets(value):
    _guards.check_flags("flags", value, valid_bits=0b011)


def test_check_flags_rejects_negative():
    with pytest.raises(ValueError):
        _guards.check_flags("flags", -1, valid_bits=0b011)


def test_check_flags_rejects_bool():
    with pytest.raises(TypeError):
        _guards.check_flags("flags", True, valid_bits=0b011)


# ===========================================================================
# check_int_range / check_uint
# ===========================================================================

def test_check_int_range_inclusive_bounds():
    _guards.check_int_range("n", 1, 1, 250)
    _guards.check_int_range("n", 250, 1, 250)


@pytest.mark.parametrize("bad", [0, 251])
def test_check_int_range_rejects_out_of_band(bad):
    with pytest.raises(ValueError):
        _guards.check_int_range("n", bad, 1, 250)


def test_check_int_range_rejects_bool():
    with pytest.raises(TypeError):
        _guards.check_int_range("n", True, 1, 250)


def test_check_uint_rejects_negative_and_overflow():
    with pytest.raises(ValueError):
        _guards.check_uint("n", -1, bits=32)
    with pytest.raises(ValueError):
        _guards.check_uint("n", 2**32, bits=32)


def test_check_uint_accepts_edges():
    _guards.check_uint("n", 0, bits=32)
    _guards.check_uint("n", 2**32 - 1, bits=32)


# ===========================================================================
# check_self_ptr
# ===========================================================================

@pytest.mark.parametrize("bad", [None, 0])
def test_check_self_ptr_rejects_null(bad):
    with pytest.raises(ValueError) as excinfo:
        _guards.check_self_ptr("self (ISteamUtils*)", bad)
    # The message should point at the real cause: init not done / not checked.
    assert "NULL" in str(excinfo.value)


def test_check_self_ptr_accepts_nonzero_pointer():
    # A non-NULL pointer-shaped value passes; the guard never dereferences it.
    _guards.check_self_ptr("self (ISteamUtils*)", 0xDEAD)


# ===========================================================================
# Real wrappers -- the guard must fire BEFORE any FFI (no_ffi sentinel).
# ===========================================================================

def test_create_lobby_bad_enum_raises_before_ffi(no_ffi):
    with pytest.raises(ValueError) as excinfo:
        steam.SteamAPI_ISteamMatchmaking_CreateLobby(0xDEAD, 99, 4)
    assert "ELobbyType" in str(excinfo.value)


def test_create_lobby_bad_member_count_raises_before_ffi(no_ffi):
    with pytest.raises(ValueError) as excinfo:
        # Enum is valid (k_ELobbyTypePublic == 2); cMaxMembers 0 is out of range.
        steam.SteamAPI_ISteamMatchmaking_CreateLobby(0xDEAD, ELobbyType.k_ELobbyTypePublic, 0)
    assert "cMaxMembers" in str(excinfo.value)


def test_send_lobby_chat_msg_str_body_raises_before_ffi(no_ffi):
    with pytest.raises(TypeError) as excinfo:
        steam.SteamAPI_ISteamMatchmaking_SendLobbyChatMsg(0xDEAD, 1, "text-not-bytes")
    assert "bytes" in str(excinfo.value)


def test_send_message_to_user_int_identity_raises_before_ffi(no_ffi):
    with pytest.raises(TypeError) as excinfo:
        steam.SteamAPI_ISteamNetworkingMessages_SendMessageToUser(
            0xDEAD, 12345, b"payload", 8, 0
        )
    # The message must name the type the caller should build instead.
    assert "SteamNetworkingIdentity" in str(excinfo.value)


def test_set_lobby_data_zero_steamid_raises_before_ffi(no_ffi):
    with pytest.raises(ValueError) as excinfo:
        steam.SteamAPI_ISteamMatchmaking_SetLobbyData(0xDEAD, 0, "k", "v")
    assert "SteamID" in str(excinfo.value)


def test_null_self_pointer_raises_before_ffi(no_ffi):
    # A NULL interface pointer is the very first guard on every interface
    # call; it must trip before we reach the sentinel library.
    with pytest.raises(ValueError) as excinfo:
        steam.SteamAPI_ISteamMatchmaking_GetLobbyOwner(None, 76561197960265728)
    assert "NULL" in str(excinfo.value)
