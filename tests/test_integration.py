"""Live integration tests -- the real Steam client must be running.

These are the "does it actually work against Valve's binary" tests. They
load the shipped dylib, init against AppID 480 (Spacewar, the test app
anyone may use), and drive the manual-dispatch pump end to end. Together
they are the live proof that the hard 20% -- the callback pump's ordering
and the call-result plumbing -- is correct against the real client, not
just against a fake.

Run them from the repo root, where steam_appid.txt (containing 480)
lives, with a logged-in Steam client running:

    python -m pytest tests/test_integration.py -q

Everything here is marked `steam`. If the prerequisites are missing the
whole module SKIPS with an instruction, rather than failing -- so a
checkout on a machine without Steam (CI, a fresh clone) stays green.

Why each wait is a bounded loop: Steam's results are asynchronous, so we
pump run_frame() at ~60 Hz and watch for what we expect, but always
against a wall-clock deadline. An unbounded "wait until it happens" loop
would hang a whole test run if Steam ever stalled; a deadline turns that
into an honest, located failure.
"""

import os
import time

import pytest

import pysteamnet as steam

# Every test in this file needs a live, logged-in Steam client.
pytestmark = pytest.mark.steam

# Where this machine's SDK keeps the macOS dylib. setdefault, not a plain
# assignment, so an outer PYSTEAMNET_LIBSTEAM_API (CI, another dev's box)
# always wins -- we only fill in a sensible default.
_DEFAULT_DYLIB_DIR = os.path.expanduser("~/Downloads/sdk/redistributable_bin/osx")

# How fast we pump, and how long we are willing to wait for each async
# result before declaring the test failed. 60 Hz mirrors a game's frame
# rate; the deadlines are generous because Steam's lobby service is a
# network round-trip.
_FRAME = 1.0 / 60.0
_LOBBY_LIST_TIMEOUT = 20.0   # RequestLobbyList queries Valve's servers
_CALL_RESULT_TIMEOUT = 15.0  # CreateLobby -> LobbyCreated_t
_CALLBACK_TIMEOUT = 10.0     # a broadcast we expect within a few frames


@pytest.fixture(scope="session")
def steam_pipe():
    """Bring the real Steam API up once for the whole module, then tear it down.

    Session-scoped on purpose: SteamAPI_InitFlat / SteamAPI_Shutdown are
    process-level, so every test shares one initialized client and one
    pipe. Yields the HSteamPipe the dispatch pump runs on.

    Skips (never fails) when a prerequisite is missing, so this file is
    safe to collect anywhere.
    """
    # Point the loader at this machine's dylib unless the environment
    # already chose one. setdefault means "default, don't override".
    os.environ.setdefault("PYSTEAMNET_LIBSTEAM_API", _DEFAULT_DYLIB_DIR)

    # The dev-mode handshake: Steam reads steam_appid.txt from the working
    # directory to learn which app we are (480). Without it InitFlat can't
    # identify us. Run this file from the repo root.
    if not os.path.isfile("steam_appid.txt"):
        pytest.skip(
            "steam_appid.txt (containing 480) not found in the working "
            "directory. Run these tests from the repo root, where the file "
            "lives:  python -m pytest tests/test_integration.py -q"
        )

    steam.load_steam_api()

    err = steam.SteamErrMsg()
    result = steam.SteamAPI_InitFlat(err)
    if result != steam.k_ESteamAPIInitResult_OK:
        # Most often: Steam isn't running, or you're not logged in. The
        # SteamErrMsg buffer carries Valve's own human-readable reason.
        pytest.skip(
            "SteamAPI_InitFlat did not succeed "
            f"({result!r}): {err.value.decode('utf-8', 'replace')!r}. "
            "These tests need a running, logged-in Steam client."
        )

    # Opt into poll-style callbacks -- the whole reason a pure-ctypes
    # binding can work. Exactly once, right after init.
    steam.SteamAPI_ManualDispatch_Init()
    pipe = steam.SteamAPI_GetHSteamPipe()
    try:
        yield pipe
    finally:
        steam.SteamAPI_Shutdown()


def _pump_until(pipe, predicate, timeout):
    """Pump run_frame() at ~60 Hz until predicate() is true or time runs out.

    predicate is called once per frame AFTER pumping; this is the single
    bounded-wait helper every test uses so no loop here can ever hang.
    Returns True if predicate became true within the deadline, else False.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        steam.run_frame(pipe)
        if predicate():
            return True
        time.sleep(_FRAME)
    return False


def _collect_until(pipe, wanted_id, timeout):
    """Pump until a broadcast callback with id `wanted_id` appears.

    Returns that callback's payload, or None on timeout. Unlike a
    call-result (keyed by handle via take_call_result), broadcast
    callbacks -- e.g. LobbyEnter_t, LobbyChatMsg_t -- arrive in
    run_frame()'s returned list, so we have to watch the list ourselves.
    """
    found = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for callback_id, payload in steam.run_frame(pipe):
            if callback_id == wanted_id:
                found["payload"] = payload
        if "payload" in found:
            return found["payload"]
        time.sleep(_FRAME)
    return None


# ===========================================================================
# 1. Init + identity: we are who we say we are, and the pipe is live.
# ===========================================================================

def test_init_and_persona(steam_pipe):
    """The smoke test: persona name, SteamID, AppID, logged-on, live pipe."""
    friends = steam.SteamAPI_SteamFriends_v018()
    name = steam.SteamAPI_ISteamFriends_GetPersonaName(friends)
    assert isinstance(name, str)
    assert name != "", "expected a non-empty persona name from a logged-in client"

    user = steam.SteamAPI_SteamUser_v023()
    my_id = steam.SteamAPI_ISteamUser_GetSteamID(user)
    assert my_id > 0, "expected a real 64-bit SteamID for the logged-in user"
    assert steam.SteamAPI_ISteamUser_BLoggedOn(user) is True

    utils = steam.SteamAPI_SteamUtils_v010()
    assert steam.SteamAPI_ISteamUtils_GetAppID(utils) == 480

    assert steam_pipe > 0, "GetHSteamPipe should be a valid (nonzero) handle"


# ===========================================================================
# 2. The pump delivers a call-result: RequestLobbyList -> LobbyMatchList_t.
#    This is the live proof that manual-dispatch ordering and the
#    GetAPICallResult plumbing (the Steamworks.NET-#413 class of bug) are
#    correct against the real client.
# ===========================================================================

def test_pump_delivers_lobby_match_list(steam_pipe):
    """RequestLobbyList's async result must land via take_call_result()."""
    mm = steam.SteamAPI_SteamMatchmaking_v009()
    call = steam.SteamAPI_ISteamMatchmaking_RequestLobbyList(mm)
    assert call != steam.k_uAPICallInvalid, "RequestLobbyList returned no call handle"

    # Pump until the completion for THIS handle is collected. The result
    # is keyed by the call handle, exactly as Valve's GetAPICallResult is.
    result_box = {}

    def collected():
        result = steam.take_call_result(call)
        if result is not None:
            result_box["result"] = result
            return True
        return False

    assert _pump_until(steam_pipe, collected, _LOBBY_LIST_TIMEOUT), (
        "RequestLobbyList's LobbyMatchList_t did not arrive within "
        f"{_LOBBY_LIST_TIMEOUT:.0f}s"
    )

    callback_id, payload, io_failed = result_box["result"]
    assert callback_id == steam.LobbyMatchList_t.k_iCallback  # 510
    assert io_failed is False, "Steam reported the lobby-list call failed in transit"
    assert isinstance(payload, steam.LobbyMatchList_t), (
        f"expected a decoded LobbyMatchList_t, got {type(payload).__name__} "
        "(a size mismatch would fall back to raw bytes -- check the struct)"
    )
    # m_nLobbiesMatching is unsigned; any non-negative count is a pass
    # (there may legitimately be zero Spacewar lobbies right now).
    assert payload.m_nLobbiesMatching >= 0


# ===========================================================================
# 3. A full single-account lobby lifecycle: create, enter, data round-trip,
#    membership, chat round-trip, leave. One account can do all of this
#    because creating a lobby puts us in it.
# ===========================================================================

def test_lobby_lifecycle_single_account(steam_pipe):
    """Create -> enter -> set/get data -> chat round-trip -> leave."""
    mm = steam.SteamAPI_SteamMatchmaking_v009()
    user = steam.SteamAPI_SteamUser_v023()
    my_id = steam.SteamAPI_ISteamUser_GetSteamID(user)

    # --- create the lobby (async; result is a LobbyCreated_t, id 513) ---
    call = steam.SteamAPI_ISteamMatchmaking_CreateLobby(
        mm, steam.k_ELobbyTypePrivate, 4
    )
    assert call != steam.k_uAPICallInvalid, "CreateLobby returned no call handle"

    # Watch for BOTH the LobbyCreated_t call-result AND the LobbyEnter_t
    # (504) broadcast in the SAME pump loop. They land within a frame or
    # two of each other, and a broadcast lives only in run_frame()'s
    # returned list -- if we stopped pumping when the call-result arrived
    # and only THEN started watching for the enter, we could miss it. So
    # this loop drains run_frame() ourselves and remembers the enter.
    created_box = {}
    enter_box = {}

    def created():
        for callback_id, broadcast in steam.run_frame(steam_pipe):
            if callback_id == steam.LobbyEnter_t.k_iCallback:
                enter_box["payload"] = broadcast
        result = steam.take_call_result(call)
        if result is not None:
            created_box["result"] = result
            return True
        return False

    # _pump_until calls created() after pumping; but created() pumps
    # itself, so pass a no-op-pumping deadline loop. We reuse the
    # deadline+sleep shape inline here because created() owns the pump.
    deadline = time.monotonic() + _CALL_RESULT_TIMEOUT
    while time.monotonic() < deadline:
        if created():
            break
        time.sleep(_FRAME)
    assert "result" in created_box, (
        f"CreateLobby's LobbyCreated_t did not arrive within {_CALL_RESULT_TIMEOUT:.0f}s"
    )

    cb_id, payload, io_failed = created_box["result"]
    assert cb_id == steam.LobbyCreated_t.k_iCallback  # 513
    assert io_failed is False, "Steam reported the CreateLobby call failed in transit"
    assert isinstance(payload, steam.LobbyCreated_t), (
        f"expected a decoded LobbyCreated_t, got {type(payload).__name__}"
    )
    assert payload.m_eResult == steam.k_EResultOK, (
        f"CreateLobby failed with EResult {payload.m_eResult}"
    )
    lobby_id = payload.m_ulSteamIDLobby
    assert lobby_id > 0

    # Everything from here uses the live lobby; LeaveLobby in the finally
    # makes sure we never leak a lobby even if an assertion below fires.
    try:
        # --- LobbyEnter_t (504): creating a lobby puts us in it, so an
        # enter broadcast for our lobby follows. The creation loop above
        # usually already captured it (enter_box); if it is a frame or two
        # behind the call-result, pump a little longer for it.
        enter = enter_box.get("payload")
        if enter is None:
            enter = _collect_until(
                steam_pipe, steam.LobbyEnter_t.k_iCallback, _CALLBACK_TIMEOUT
            )
        assert enter is not None, (
            f"no LobbyEnter_t (504) within {_CALLBACK_TIMEOUT:.0f}s of creating the lobby"
        )
        assert isinstance(enter, steam.LobbyEnter_t)
        assert enter.m_ulSteamIDLobby == lobby_id

        # --- lobby data round-trips through Steam ---
        assert steam.SteamAPI_ISteamMatchmaking_SetLobbyData(
            mm, lobby_id, "game_mode", "coop"
        ) is True
        assert steam.SteamAPI_ISteamMatchmaking_GetLobbyData(
            mm, lobby_id, "game_mode"
        ) == "coop"

        # --- membership: just us, and we own it ---
        assert steam.SteamAPI_ISteamMatchmaking_GetNumLobbyMembers(mm, lobby_id) == 1
        assert steam.SteamAPI_ISteamMatchmaking_GetLobbyOwner(mm, lobby_id) == my_id

        # --- chat round-trips: send b"ping", pump until LobbyChatMsg_t ---
        assert steam.SteamAPI_ISteamMatchmaking_SendLobbyChatMsg(
            mm, lobby_id, b"ping"
        ) is True

        chat = _collect_until(steam_pipe, steam.LobbyChatMsg_t.k_iCallback, _CALLBACK_TIMEOUT)
        assert chat is not None, (
            f"no LobbyChatMsg_t (507) within {_CALLBACK_TIMEOUT:.0f}s of sending chat"
        )
        assert isinstance(chat, steam.LobbyChatMsg_t)
        assert chat.m_ulSteamIDLobby == lobby_id

        data, sender, entry_type = steam.SteamAPI_ISteamMatchmaking_GetLobbyChatEntry(
            mm, lobby_id, chat.m_iChatID
        )
        assert data == b"ping"
        assert sender == my_id
        # 1 == k_EChatEntryTypeChatMsg, a normal chat message.
        assert entry_type == steam.k_EChatEntryTypeChatMsg
    finally:
        steam.SteamAPI_ISteamMatchmaking_LeaveLobby(mm, lobby_id)
