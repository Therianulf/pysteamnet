#!/usr/bin/env python3
"""messages_pingpong.py -- reliable round-trips over ISteamNetworkingMessages (M3).

This is the transport acceptance test and the demo of the layer Bjorn's
World's networking will sit on. One side LISTENS and echoes; the other
side CONNECTS, fires 20 numbered reliable messages, and checks that all 20
come back in order, byte-identical. If they do, the transport works.

WHAT THIS DEMONSTRATES
    ISteamNetworkingMessages end to end: starting a session, accepting an
    incoming session (SteamNetworkingMessagesSessionRequest_t ->
    AcceptSessionWithUser), sending reliable datagrams addressed by SteamID,
    receiving them with ReceiveMessagesOnChannel, and handling a failed
    session (SteamNetworkingMessagesSessionFailed_t).

ACCOUNTS / MACHINES YOU NEED  (read this before you start!)
    REQUIRES TWO MACHINES, TWO ACCOUNTS, AND -- for relay routing to find a
    path -- THE TWO ACCOUNTS SHOULD BE STEAM FRIENDS. You cannot run both
    roles on one machine (two logged-in Steam clients can't share a box).
    Get each side's SteamID64 from hello_steam.py (it prints your own id).
    Both machines need a steam_appid.txt containing 480.

PREREQUISITES (each machine)
    * Steam running and logged in.
    * steam_appid.txt with 480 in the working directory (run from repo root).
    * Valve's steam_api library findable, e.g.:
          export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx

HOW TO RUN
    On the machine that will echo:
        python examples/messages_pingpong.py listen
        (note its SteamID64 -- the connector needs it)
    On the other machine:
        python examples/messages_pingpong.py connect <listener_steamid64>

WHAT YOU'LL SEE
    listen: "session accepted from <id>", then a quiet echo loop. Ctrl-C to quit.
    connect: 20 sends, then echoes arriving, then a PASS/FAIL verdict.

EXIT CRITERIA
    connect prints "PASS: 20/20 reliable round-trips, in order" and exits 0
    when every message came back in order and unchanged; otherwise it prints
    what was missing or out of order and exits 1. listen exits 0 on Ctrl-C.
"""

import signal
import sys
import time

import pysteamnet as steam

FRAME = 1 / 60
CHANNEL = 0
COUNT = 20
COLLECT_SECONDS = 30.0


def init_steam():
    """Load the library, connect to Steam, opt into manual dispatch.

    Returns (pipe, messages_interface). Exits clearly if Steam is unreachable.
    """
    steam.load_steam_api()
    err = steam.SteamErrMsg()
    if steam.SteamAPI_InitFlat(err) != steam.k_ESteamAPIInitResult_OK:
        raise SystemExit(
            "Steam init failed: " + err.value.decode("utf-8", "replace") +
            "\n(Is Steam running and logged in? Is steam_appid.txt (480) here?)"
        )
    steam.SteamAPI_ManualDispatch_Init()
    # SteamAPI_InitFlat installs steamclient's own SIGINT handler, which
    # would swallow Ctrl-C; re-assert Python's so the listen role's Ctrl-C
    # cleanup still runs.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    pipe = steam.SteamAPI_GetHSteamPipe()
    messages = steam.SteamAPI_SteamNetworkingMessages_SteamAPI_v002()
    return pipe, messages


def make_identity(steamid64):
    """Build a SteamNetworkingIdentity naming the user with this SteamID64.

    We use Valve's own flat helper so the identity's internal layout stays
    Valve's responsibility, never ours.
    """
    ident = steam.SteamNetworkingIdentity()
    steam.SteamAPI_SteamNetworkingIdentity_SetSteamID64(ident, steamid64)
    return ident


def report_session_failure(payload):
    """Print why a session failed, from a SteamNetworkingMessagesSessionFailed_t."""
    reason = payload.m_info.m_eEndReason
    debug = payload.m_info.m_szEndDebug.decode("utf-8", "replace")
    print(f"SESSION FAILED: end reason {reason}: {debug}")


def run_listen():
    """Accept incoming sessions and echo every message back to its sender."""
    pipe, messages = init_steam()
    user = steam.SteamAPI_SteamUser_v023()
    my_id = steam.SteamAPI_ISteamUser_GetSteamID(user)
    print(f"Listening as SteamID {my_id}. Tell the connector to use this id.")
    print("Echoing every message back (Ctrl-C to quit)...")

    # Remember peers we've accepted, so we can close their sessions on exit.
    peers = set()
    try:
        while True:
            for callback_id, payload in steam.run_frame(pipe):
                if callback_id == steam.SteamNetworkingMessagesSessionRequest_t.k_iCallback:
                    # A new peer wants to talk and no session exists yet. The
                    # callback's m_identityRemote IS a SteamNetworkingIdentity,
                    # so we hand it straight to AcceptSessionWithUser.
                    ident = payload.m_identityRemote
                    peer_id = steam.SteamAPI_SteamNetworkingIdentity_GetSteamID64(ident)
                    steam.SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser(
                        messages, ident
                    )
                    peers.add(peer_id)
                    print(f"session accepted from {peer_id}")
                elif callback_id == steam.SteamNetworkingMessagesSessionFailed_t.k_iCallback:
                    report_session_failure(payload)

            # Drain the channel and bounce each message straight back to its
            # sender on the same channel, reliably and unchanged.
            for msg in steam.SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
                messages, CHANNEL
            ):
                reply_to = make_identity(msg.sender_steamid64)
                steam.SteamAPI_ISteamNetworkingMessages_SendMessageToUser(
                    messages, reply_to, msg.data,
                    steam.k_nSteamNetworkingSend_Reliable, msg.channel,
                )
            time.sleep(FRAME)
    except KeyboardInterrupt:
        print("\nClosing sessions and shutting down.")
        for peer_id in peers:
            # Best-effort cleanup -- the peer gets no notification (UDP-style).
            steam.SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser(
                messages, make_identity(peer_id)
            )
        steam.SteamAPI_Shutdown()
        return 0


def run_connect(peer_steamid64):
    """Send 20 numbered reliable pings and verify all 20 echo back, in order."""
    pipe, messages = init_steam()
    peer = make_identity(peer_steamid64)

    # The 20 payloads we expect to get back, in this exact order.
    expected = [f"ping {n}".encode("ascii") for n in range(COUNT)]

    # Send one per frame so the prints interleave readably; each send's
    # EResult is checked -- anything but k_EResultOK is a hard failure.
    print(f"Connecting to {peer_steamid64}, sending {COUNT} reliable pings...")
    for n in range(COUNT):
        # Pump first so an inbound SessionFailed surfaces before we keep sending.
        for callback_id, payload in steam.run_frame(pipe):
            if callback_id == steam.SteamNetworkingMessagesSessionFailed_t.k_iCallback:
                report_session_failure(payload)
                steam.SteamAPI_Shutdown()
                return 1
        result = steam.SteamAPI_ISteamNetworkingMessages_SendMessageToUser(
            messages, peer, expected[n],
            steam.k_nSteamNetworkingSend_Reliable, CHANNEL,
        )
        if result != steam.k_EResultOK:
            # SendMessageToUser returns an EResult enum (or a raw int for a
            # value this SDK doesn't know); both print readably here.
            print(f"send {n} failed: {result!r}")
            steam.SteamAPI_Shutdown()
            return 1
        time.sleep(FRAME)
    print(f"All {COUNT} pings sent. Collecting echoes (up to {int(COLLECT_SECONDS)}s)...")

    # Collect echoes until we have all of them or the deadline passes.
    received = []
    deadline = time.monotonic() + COLLECT_SECONDS
    while len(received) < COUNT and time.monotonic() < deadline:
        for callback_id, payload in steam.run_frame(pipe):
            if callback_id == steam.SteamNetworkingMessagesSessionFailed_t.k_iCallback:
                report_session_failure(payload)
                steam.SteamAPI_Shutdown()
                return 1
        for msg in steam.SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
            messages, CHANNEL
        ):
            received.append(msg.data)
        time.sleep(FRAME)

    # Verdict. The reliable channel guarantees in-order delivery, so a correct
    # run has received == expected exactly.
    steam.SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser(messages, peer)
    steam.SteamAPI_Shutdown()

    if received == expected:
        print("PASS: 20/20 reliable round-trips, in order")
        return 0

    # Explain exactly what went wrong.
    got = len(received)
    print(f"FAIL: received {got}/{COUNT} echoes.")
    missing = [m for m in expected if m not in received]
    if missing:
        print(f"  missing: {[m.decode() for m in missing]}")
    if received != expected[:got]:
        print(f"  out of order or corrupted: {[m.decode('ascii', 'replace') for m in received]}")
    return 1


def main(argv):
    if len(argv) >= 2 and argv[1] == "listen":
        return run_listen()
    if len(argv) == 3 and argv[1] == "connect":
        try:
            peer = int(argv[2])
        except ValueError:
            raise SystemExit(f"peer id must be an integer SteamID64, got {argv[2]!r}")
        return run_connect(peer)
    raise SystemExit(
        "usage:\n"
        "    python examples/messages_pingpong.py listen\n"
        "    python examples/messages_pingpong.py connect <peer_steamid64>"
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
