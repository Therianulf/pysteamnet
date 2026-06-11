"""The managed receive wrapper: copy everything, release everything, always.

SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel is the one
deliberately-managed wrapper in pysteamnet: the C call hands back
message pointers that MUST each be released exactly once, so the
wrapper copies every payload to Python bytes and releases every message
itself. These tests drive it against a fake library holding real
SteamNetworkingMessage_t structs and pin the two properties that
two-machine live testing can't easily cover:

  * every message Steam hands us is released exactly once, and
  * that stays true even if copying one of the messages raises
    mid-loop (the leak class the adversarial review flagged).
"""

import ctypes

import pytest

import pysteamnet
from pysteamnet import _loader
from pysteamnet._structs import SteamNetworkingMessage_t

SELF_PTR = 0xDEAD  # any non-NULL token; the fake never dereferences it.


class _FakeMessagesLib:
    """Hands out real SteamNetworkingMessage_t structs like the C API does.

    Owns the message structs and their payload buffers (so the pointers
    the wrapper reads stay alive), logs every Release, and can be told
    to blow up on the Nth GetSteamID64 call to simulate a mid-copy
    failure.
    """

    def __init__(self, payloads, explode_on_call=None):
        self.released = []
        self._steamid_calls = 0
        self._explode_on_call = explode_on_call
        self._buffers = []   # keep payload memory alive
        self._messages = []  # keep the structs alive
        for n, data in enumerate(payloads):
            buf = ctypes.create_string_buffer(data, len(data))
            msg = SteamNetworkingMessage_t()
            msg.m_pData = ctypes.cast(buf, ctypes.c_void_p)
            msg.m_cbSize = len(data)
            msg.m_nChannel = 0
            msg.m_nFlags = 8  # reliable
            msg.m_nMessageNumber = n + 1
            self._buffers.append(buf)
            self._messages.append(msg)

    def SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
        self, self_ptr, channel, ptrs, n_max
    ):
        n = min(len(self._messages), n_max)
        for i in range(n):
            ptrs[i] = ctypes.pointer(self._messages[i])
        return n

    def SteamAPI_SteamNetworkingIdentity_GetSteamID64(self, pident):
        self._steamid_calls += 1
        if self._steamid_calls == self._explode_on_call:
            raise RuntimeError("simulated mid-copy failure")
        return 76561198000000000 + self._steamid_calls

    def SteamAPI_SteamNetworkingMessage_t_Release(self, ptr):
        self.released.append(ctypes.addressof(ptr.contents))


@pytest.fixture
def fake_lib(monkeypatch):
    """Install a fake as the loaded library; the test fills in messages."""
    def install(payloads, explode_on_call=None):
        fake = _FakeMessagesLib(payloads, explode_on_call)
        monkeypatch.setattr(_loader, "_lib", fake)
        return fake
    yield install


def test_receive_copies_payloads_and_releases_each_message_once(fake_lib):
    fake = fake_lib([b"alpha", b"beta\x00with-nul", b"gamma"])

    out = pysteamnet.SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
        SELF_PTR, 0, nMaxMessages=8
    )

    assert [m.data for m in out] == [b"alpha", b"beta\x00with-nul", b"gamma"]
    assert [m.message_number for m in out] == [1, 2, 3]
    assert all(m.flags == 8 for m in out)

    expected = [ctypes.addressof(m) for m in fake._messages]
    assert fake.released == expected, "every message released, in order, once"


def test_receive_releases_everything_even_when_a_copy_raises(fake_lib):
    fake = fake_lib([b"one", b"two", b"three"], explode_on_call=2)

    with pytest.raises(RuntimeError, match="simulated mid-copy failure"):
        pysteamnet.SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
            SELF_PTR, 0, nMaxMessages=8
        )

    # The copy of message #2 raised -- but ALL THREE messages Steam
    # handed us must still go back to Steam's pool exactly once each.
    expected = [ctypes.addressof(m) for m in fake._messages]
    assert fake.released == expected, "no message may leak on a mid-loop error"


def test_receive_empty_channel_returns_empty_list(fake_lib):
    fake = fake_lib([])

    out = pysteamnet.SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
        SELF_PTR, 0
    )

    assert out == []
    assert fake.released == []
