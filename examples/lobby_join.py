#!/usr/bin/env python3
"""lobby_join.py -- join a lobby someone else created (M2 demo, joiner half).

This is the JOINER half of the lobby pair. Give it the lobby id that
lobby_host.py printed; it joins the lobby, reads back the lobby's "name",
lists the members it can see, sends one chat message, and leaves.

WHAT THIS DEMONSTRATES
    JoinLobby's call-result (LobbyEnter_t), reading lobby data and the
    member list, and sending a lobby chat message -- the joiner's side of
    the same async-call + broadcast patterns the host demonstrates.

ACCOUNTS / MACHINES YOU NEED  (read this before you start!)
    THIS REQUIRES A SECOND ACCOUNT ON A SECOND MACHINE. Two logged-in Steam
    clients cannot share one machine, so the joiner cannot be the same
    computer that is running lobby_host.py. The host's account and this
    account being Steam friends is the simplest way for a friends-only
    lobby to be joinable. Get the lobby id from the host's terminal.

PREREQUISITES
    * Steam client installed, running, and logged in (as the joiner).
    * A steam_appid.txt containing 480 (Spacewar) in your working directory
      -- the repo root has one; run this FROM the repo root.
    * Valve's steam_api library findable by the loader, e.g.:
          export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx

HOW TO RUN  (from the repo root)
    python examples/lobby_join.py <lobby_steamid64>
        e.g. python examples/lobby_join.py 109775244...

WHAT YOU'LL SEE
    "Joined lobby ...", the lobby name, the member count, and one line per
    member (SteamID + persona name), then "Sent chat message".

EXIT CRITERIA
    Success = we entered the lobby (m_EChatRoomEnterResponse == Success),
    listed members, and sent a chat message -> exit 0. If the enter response
    is anything else, the response name is printed and we exit 1.
"""

import signal
import sys
import time

import pysteamnet as steam

FRAME = 1 / 60


def init_steam():
    """Load the library, connect to Steam, opt into manual dispatch; return pipe."""
    steam.load_steam_api()
    err = steam.SteamErrMsg()
    if steam.SteamAPI_InitFlat(err) != steam.k_ESteamAPIInitResult_OK:
        raise SystemExit(
            "Steam init failed: " + err.value.decode("utf-8", "replace") +
            "\n(Is Steam running and logged in? Is steam_appid.txt (480) here?)"
        )
    steam.SteamAPI_ManualDispatch_Init()
    # SteamAPI_InitFlat installs steamclient's own SIGINT handler, which
    # would swallow Ctrl-C; re-assert Python's so Ctrl-C still works.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    return steam.SteamAPI_GetHSteamPipe()


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: python examples/lobby_join.py <lobby_steamid64>")
    try:
        lobby_id = int(argv[1])
    except ValueError:
        raise SystemExit(f"lobby id must be an integer SteamID64, got {argv[1]!r}")

    pipe = init_steam()
    matchmaking = steam.SteamAPI_SteamMatchmaking_v009()
    friends = steam.SteamAPI_SteamFriends_v018()

    # Ask to join. Returns a handle; the result is a LobbyEnter_t (id 504).
    print(f"Joining lobby {lobby_id}...")
    call = steam.SteamAPI_ISteamMatchmaking_JoinLobby(matchmaking, lobby_id)
    if call == steam.k_uAPICallInvalid:
        raise SystemExit("JoinLobby was rejected immediately by Steam.")

    # Pump until the call-result lands.
    entered = None
    while entered is None:
        steam.run_frame(pipe)
        result = steam.take_call_result(call)
        if result is not None:
            _id, entered, _io_failed = result
        time.sleep(FRAME)

    # m_EChatRoomEnterResponse == 1 (Success) means we're in. Anything else
    # is a refusal; print the readable name and bail.
    if entered.m_EChatRoomEnterResponse != steam.k_EChatRoomEnterResponseSuccess:
        name = steam.EChatRoomEnterResponse(entered.m_EChatRoomEnterResponse)
        print(f"Could not enter lobby: {name!r}")
        return 1

    print(f"Joined lobby {lobby_id}.")

    # Read the lobby's shared "name" value the host set.
    lobby_name = steam.SteamAPI_ISteamMatchmaking_GetLobbyData(
        matchmaking, lobby_id, "name"
    )
    print(f"Lobby name: {lobby_name!r}")

    # List the members. GetFriendPersonaName may return "" for accounts that
    # are strangers to this client (names are only cached for friends and
    # recent peers); that's expected, not an error.
    count = steam.SteamAPI_ISteamMatchmaking_GetNumLobbyMembers(matchmaking, lobby_id)
    print(f"Members: {count}")
    for i in range(count):
        member = steam.SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex(
            matchmaking, lobby_id, i
        )
        persona = steam.SteamAPI_ISteamFriends_GetFriendPersonaName(friends, member)
        shown = persona if persona else "(name unknown to this client)"
        print(f"  {member}  {shown}")

    # Send one lobby chat message. Everyone in the lobby (including the host)
    # receives a LobbyChatMsg_t and reads the body with GetLobbyChatEntry.
    steam.SteamAPI_ISteamMatchmaking_SendLobbyChatMsg(
        matchmaking, lobby_id, b"hello from joiner"
    )
    print("Sent chat message.")

    # Pump a few more seconds so the chat send and any data updates flush
    # before we leave.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        steam.run_frame(pipe)
        time.sleep(FRAME)

    steam.SteamAPI_ISteamMatchmaking_LeaveLobby(matchmaking, lobby_id)
    steam.SteamAPI_Shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
