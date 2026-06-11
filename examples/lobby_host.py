#!/usr/bin/env python3
"""lobby_host.py -- create a lobby and watch who comes and goes (M2 demo).

This is the HOST half of the lobby pair. It creates a friends-only lobby,
prints the lobby's SteamID so a second person can join it, names the lobby
"pysteamnet-demo", and then sits in a pump loop reporting every join, leave,
and data change until you press Ctrl-C.

WHAT THIS DEMONSTRATES
    The async call-result pattern (CreateLobby returns a handle; the real
    LobbyCreated_t result arrives later, collected with take_call_result),
    plus the lobby broadcast callbacks: LobbyChatUpdate_t (members coming
    and going) and LobbyDataUpdate_t (lobby/member metadata changing).

ACCOUNTS / MACHINES YOU NEED  (read this before you start!)
    * This script needs ONE Steam account -- the host. Run it on your machine.
    * To see anything interesting, a SECOND account on a SECOND machine must
      join, by running:
          python examples/lobby_join.py <the lobby id this prints>
      Two logged-in Steam clients cannot share one machine, so the joiner
      really does need to be elsewhere (a friend, your other PC, your son's
      computer). A friends-only lobby is visible to friends of its members,
      so the two accounts being Steam friends is the simplest setup.
    * You can also run host alone just to confirm a lobby gets created; you
      simply won't see any join/leave traffic.

PREREQUISITES
    * Steam client installed, running, and logged in.
    * A steam_appid.txt containing 480 (Spacewar) in your working directory.
      It is gitignored; create it once (echo 480 > steam_appid.txt) and run
      this FROM the repo root.
    * Valve's steam_api library findable by the loader. The simplest way in
      development is to point at the SDK copy:
          export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx

HOW TO RUN  (from the repo root)
    python examples/lobby_host.py

WHAT YOU'LL SEE
    A clearly-boxed lobby id line you copy to the joiner, then -- once the
    joiner connects -- lines like "JOIN  <steamid>" and "LEFT  <steamid>".

EXIT CRITERIA
    Success = the lobby id prints (the lobby was created on Steam's servers).
    Press Ctrl-C to stop; the script leaves the lobby cleanly and exits 0.
"""

import signal
import sys
import time

import pysteamnet as steam

# Pump roughly 60 times a second, like a game's main loop would.
FRAME = 1 / 60


def init_steam():
    """Load the library, connect to Steam, opt into manual dispatch.

    Returns the pipe handle the pump runs on. Exits with a clear message
    if Steam isn't reachable (almost always: not running, not logged in,
    or no steam_appid.txt in the working directory).
    """
    steam.load_steam_api()
    err = steam.SteamErrMsg()
    if steam.SteamAPI_InitFlat(err) != steam.k_ESteamAPIInitResult_OK:
        raise SystemExit(
            "Steam init failed: " + err.value.decode("utf-8", "replace") +
            "\n(Is Steam running and logged in? Is steam_appid.txt (480) here?)"
        )
    steam.SteamAPI_ManualDispatch_Init()
    # Surprising but real: SteamAPI_InitFlat installs steamclient's own
    # SIGINT handler, which swallows Ctrl-C -- so our `except KeyboardInterrupt`
    # cleanup would never run. Re-assert Python's default handler so Ctrl-C
    # raises KeyboardInterrupt again. (A real game with its own signal
    # handling would integrate this differently; for a script, this is the fix.)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    return steam.SteamAPI_GetHSteamPipe()


def main():
    pipe = init_steam()
    matchmaking = steam.SteamAPI_SteamMatchmaking_v009()

    # Ask Steam to create a friends-only lobby for up to 4 players. This
    # returns immediately with a handle; the actual lobby arrives later as
    # a LobbyCreated_t (id 513) call-result.
    call = steam.SteamAPI_ISteamMatchmaking_CreateLobby(
        matchmaking, steam.k_ELobbyTypeFriendsOnly, 4
    )
    if call == steam.k_uAPICallInvalid:
        raise SystemExit("CreateLobby was rejected immediately by Steam.")

    # Pump until the call-result lands. take_call_result(handle) returns None
    # while the call is still in flight, then (callback_id, payload, io_failed).
    print("Creating lobby...")
    lobby_id = None
    while lobby_id is None:
        steam.run_frame(pipe)
        result = steam.take_call_result(call)
        if result is not None:
            _id, created, io_failed = result
            if io_failed or created.m_eResult != steam.k_EResultOK:
                raise SystemExit(
                    f"Lobby creation failed: EResult={created.m_eResult}, "
                    f"io_failed={io_failed}"
                )
            lobby_id = created.m_ulSteamIDLobby
        time.sleep(FRAME)

    # Give the lobby a human-readable name. Members (and friends searching)
    # can read this back with GetLobbyData(lobby, "name").
    steam.SteamAPI_ISteamMatchmaking_SetLobbyData(
        matchmaking, lobby_id, "name", "pysteamnet-demo"
    )

    # Print the lobby id prominently -- this is the one number the joiner needs.
    print()
    print("=" * 60)
    print(f"  LOBBY READY -- id: {lobby_id}")
    print(f"  give this to the joiner:")
    print(f"      python examples/lobby_join.py {lobby_id}")
    print("=" * 60)
    print()
    print("Watching for members (Ctrl-C to quit)...")

    try:
        # Pump forever, reporting lobby traffic as it arrives.
        while True:
            for callback_id, payload in steam.run_frame(pipe):
                if callback_id == steam.LobbyChatUpdate_t.k_iCallback:  # 506
                    # A member joined, left, or was removed. The state-change
                    # field is an EChatMemberStateChange bitfield; decode it
                    # to a readable name (it can in principle be a combination).
                    who = payload.m_ulSteamIDUserChanged
                    flags = steam.EChatMemberStateChange(
                        payload.m_rgfChatMemberStateChange
                    )
                    # A friendly verb for the common single-bit cases.
                    if flags & steam.k_EChatMemberStateChangeEntered:
                        verb = "JOIN"
                    elif flags & steam.k_EChatMemberStateChangeLeft:
                        verb = "LEFT"
                    else:
                        verb = "CHANGE"
                    print(f"{verb}  {who}  ({flags!r})")

                elif callback_id == steam.LobbyDataUpdate_t.k_iCallback:  # 505
                    # If the changed "member" equals the lobby itself, the
                    # lobby's own data changed; otherwise a member's data did.
                    if payload.m_ulSteamIDMember == payload.m_ulSteamIDLobby:
                        print(f"DATA  lobby data changed (lobby {payload.m_ulSteamIDLobby})")
                    else:
                        print(f"DATA  member data changed (member {payload.m_ulSteamIDMember})")
            time.sleep(FRAME)
    except KeyboardInterrupt:
        # Tidy exit: leave the lobby (other members see a LobbyChatUpdate_t)
        # and shut the API down.
        print("\nLeaving lobby and shutting down.")
        steam.SteamAPI_ISteamMatchmaking_LeaveLobby(matchmaking, lobby_id)
        steam.SteamAPI_Shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
