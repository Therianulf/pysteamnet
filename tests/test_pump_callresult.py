"""The async call-result path -- where the famous manual-dispatch bug lives.

When an async call (CreateLobby, RequestLobbyList, ...) finishes, Steam
posts a SteamAPICallCompleted_t (id 703) whose INNER fields describe the
real result: which handle completed, what result struct it is, and how
big that struct is. The pump must then fetch the result with
GetAPICallResult using the INNER struct's handle/size/id -- using the
OUTER 703's values instead is the Steamworks.NET-#413 regression class,
and it is exactly the kind of mistake that survives code review.

These tests drive the pump's call-result branch through FakeSteamLib and
assert:
  * GetAPICallResult is called with the INNER handle, size, and id.
  * the decoded result lands both in run_frame's returned list and in the
    per-handle buffer that take_call_result drains.
  * a failed-in-transit result is still delivered, but flagged.
  * a declined fetch (GetAPICallResult returns false) delivers/stores
    nothing -- yet the callback slot is still freed.
"""

import ctypes

import pytest

from pysteamnet import _dispatch
from pysteamnet._structs import LobbyMatchList_t, SteamAPICallCompleted_t
from tests.fakes.fake_steam_lib import FakeSteamLib

PIPE = 7
HANDLE = 42
RESULT_ID = LobbyMatchList_t.k_iCallback  # 510


@pytest.fixture(autouse=True)
def clear_pending_results():
    """The pump's call-result buffer is module-global; isolate every test.

    take_call_result pops from _dispatch._pending_call_results, but a test
    that never drains its handle would leak into the next test. Clear it
    before and after each test so assertions about "what's stored" are
    about this test alone.
    """
    _dispatch._pending_call_results.clear()
    yield
    _dispatch._pending_call_results.clear()


def _match_list_bytes(n):
    s = LobbyMatchList_t()
    s.m_nLobbiesMatching = n
    return bytes(s)


# ---------------------------------------------------------------------------
# a. The happy path: inner args used, result delivered AND stored, then popped.
# ---------------------------------------------------------------------------

def test_callresult_uses_inner_args_and_delivers_and_stores():
    result_bytes = _match_list_bytes(7)
    fake = FakeSteamLib([
        ("callresult", HANDLE, RESULT_ID, result_bytes, False, True),
    ])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    # -- GetAPICallResult was called with the INNER struct's values --------
    getapi = [e for e in fake.call_log if e[0] == "GetAPICallResult"]
    assert len(getapi) == 1, "exactly one result fetch for one completion"
    _, pipe, hCall, pCallback, cub, iExpected, pbFailed = getapi[0]
    assert pipe == PIPE
    assert hCall == HANDLE, "handle must come from the INNER struct"
    assert cub == len(result_bytes), "size must come from the INNER m_cubParam"
    assert iExpected == RESULT_ID, "expected id is the INNER m_iCallback (510), not 703"
    assert iExpected != SteamAPICallCompleted_t.k_iCallback
    # The buffer the pump allocated must be exactly cub bytes wide.
    assert ctypes.sizeof(pCallback) == cub

    # -- the decoded result appears in run_frame's returned list -----------
    assert len(delivered) == 1
    cb_id, payload = delivered[0]
    assert cb_id == RESULT_ID
    assert isinstance(payload, LobbyMatchList_t)
    assert payload.m_nLobbiesMatching == 7

    # -- and is keyed by handle for take_call_result -----------------------
    taken = _dispatch.take_call_result(HANDLE)
    assert taken is not None
    result_id, stored_payload, io_failed = taken
    assert result_id == RESULT_ID
    assert isinstance(stored_payload, LobbyMatchList_t)
    assert stored_payload.m_nLobbiesMatching == 7
    assert io_failed is False

    # -- the second take pops nothing (it was already drained) -------------
    assert _dispatch.take_call_result(HANDLE) is None


# ---------------------------------------------------------------------------
# b. failed=True: still delivered/stored, but io_failed is True.
# ---------------------------------------------------------------------------

def test_callresult_failed_flag_is_recorded():
    result_bytes = _match_list_bytes(3)
    fake = FakeSteamLib([
        ("callresult", HANDLE, RESULT_ID, result_bytes, True, True),
    ])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    # The payload is still delivered to the frame list...
    assert len(delivered) == 1
    cb_id, payload = delivered[0]
    assert cb_id == RESULT_ID
    assert payload.m_nLobbiesMatching == 3

    # ...and stored, but flagged as failed in transit.
    taken = _dispatch.take_call_result(HANDLE)
    assert taken is not None
    result_id, stored_payload, io_failed = taken
    assert io_failed is True, "pbFailed=true must surface as io_failed=True"
    assert stored_payload.m_nLobbiesMatching == 3


# ---------------------------------------------------------------------------
# c. fetch_ok=False: nothing delivered/stored, but the slot is still freed.
# ---------------------------------------------------------------------------

def test_callresult_fetch_declined_delivers_nothing_but_frees():
    result_bytes = _match_list_bytes(5)
    fake = FakeSteamLib([
        ("callresult", HANDLE, RESULT_ID, result_bytes, False, False),
    ])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    # GetAPICallResult returned false -> the pump must drop this event.
    assert delivered == [], "a declined fetch delivers nothing"
    assert _dispatch.take_call_result(HANDLE) is None, "nothing stored either"

    # But the callback slot is still freed -- the finally protects the pipe
    # whether or not the result came through.
    names = [e[0] for e in fake.call_log]
    assert names.count("FreeLastCallback") == 1
    # And GetAPICallResult was attempted exactly once before the free.
    assert names.count("GetAPICallResult") == 1
    assert names.index("GetAPICallResult") < names.index("FreeLastCallback")


# ---------------------------------------------------------------------------
# d. The per-handle buffer is bounded: oldest entries are evicted, never
#    grown forever, so callers who only read run_frame's list can safely
#    ignore handles for the life of the process.
# ---------------------------------------------------------------------------

def test_pending_call_results_evicts_oldest_at_cap(monkeypatch):
    monkeypatch.setattr(_dispatch, "_PENDING_CALL_RESULTS_MAX", 2)
    fake = FakeSteamLib([
        ("callresult", 101, RESULT_ID, _match_list_bytes(1), False, True),
        ("callresult", 102, RESULT_ID, _match_list_bytes(2), False, True),
        ("callresult", 103, RESULT_ID, _match_list_bytes(3), False, True),
    ])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    # Every completion is still delivered to the frame list (the cap only
    # bounds the keep-until-popped buffer, it never drops live events)...
    assert [p.m_nLobbiesMatching for _, p in delivered] == [1, 2, 3]

    # ...but the buffer holds only the newest two: 101 was evicted.
    assert _dispatch.take_call_result(101) is None, "oldest entry evicted at cap"
    assert _dispatch.take_call_result(102)[1].m_nLobbiesMatching == 2
    assert _dispatch.take_call_result(103)[1].m_nLobbiesMatching == 3


# ---------------------------------------------------------------------------
# e. A 703 whose outer payload is the wrong size is never trusted: reading
#    the inner fields would over-read the buffer, so the pump falls back to
#    raw-bytes delivery (and still frees), and never calls GetAPICallResult.
# ---------------------------------------------------------------------------

def test_short_703_payload_falls_back_to_raw_bytes():
    short = b"\x01\x02\x03"  # 3 bytes where SteamAPICallCompleted_t needs 16
    fake = FakeSteamLib([
        ("callback", SteamAPICallCompleted_t.k_iCallback, short),
    ])

    delivered = _dispatch.run_frame(PIPE, lib=fake)

    assert delivered == [(SteamAPICallCompleted_t.k_iCallback, short)], (
        "a malformed completion notice is delivered as raw bytes, not decoded"
    )
    names = [e[0] for e in fake.call_log]
    assert names.count("GetAPICallResult") == 0, "no fetch from a short notice"
    assert names.count("FreeLastCallback") == 1, "the slot is still freed"
