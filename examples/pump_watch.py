#!/usr/bin/env python3
"""pump_watch.py -- watch the manual-dispatch callback loop in real time.

hello_steam.py proves you can talk to Steam. This example makes the OTHER
half of the binding visible: the callback pump. Steam delivers events --
friends coming online, lobby changes, async results -- as "callbacks". A
pure-ctypes binding can't let a Steam thread call into Python, so instead
we poll a queue once per frame with pysteamnet.run_frame(). This script
runs that pump for 30 seconds and prints one line for every callback it
sees, so you can literally watch the events flow.

Each line looks like:

    [t+12.34] id=304 PersonaStateChange_t

The id is Valve's numeric callback id; the name is resolved from
pysteamnet.CALLBACK_REGISTRY (the same id->struct map the pump itself
uses). Callbacks we don't have a struct for are still delivered -- never
hidden, never dropped -- as raw bytes, and shown like:

    [t+05.01] id=1521 unknown, delivered as 24 raw bytes, freed

------------------------------------------------------------------------
GENERATING SOME TRAFFIC TO WATCH
------------------------------------------------------------------------
A quiet account may see nothing for a while -- that's correct, not a bug.
To make events happen while it runs, try any of these:

    * open the friends list, or open the Steam overlay (Shift+Tab)
    * have a friend go online / offline / change their status
      (each produces a PersonaStateChange_t, id 304)
    * launch or quit another Steam game on a friend's account

------------------------------------------------------------------------
PREREQUISITES  (identical to hello_steam.py -- read that file's header for
the full version)
------------------------------------------------------------------------
    1. Steam client running and logged in.
    2. steam_appid.txt containing 480 in the directory you run from
       (the repo root has one).
    3. Valve's Steam library findable -- set PYSTEAMNET_LIBSTEAM_API, e.g.:
           export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx

------------------------------------------------------------------------
HOW TO RUN (from the repo root)
------------------------------------------------------------------------
    env PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx \
        python examples/pump_watch.py

------------------------------------------------------------------------
WHAT YOU SHOULD SEE
------------------------------------------------------------------------
    Connected as YourName. Pumping callbacks for 30 seconds...
    (Open your friends list or the Steam overlay to generate some traffic.)

    [t+00.02] id=304 PersonaStateChange_t
    [t+11.40] id=304 PersonaStateChange_t
    ...

    2 callbacks in 30s, clean shutdown

The exact callbacks depend entirely on what your account does during the
window. Zero callbacks is a perfectly valid (if quiet) result.

------------------------------------------------------------------------
EXIT CODES
------------------------------------------------------------------------
    0  success -- ran the full window and shut down cleanly
    1  failure -- the library wasn't found, or init failed
"""

import sys
import time

import pysteamnet as steam


# How long to watch, and how fast to pump. 60 Hz mirrors a game's main
# loop -- the pump is meant to be called once per rendered frame.
WATCH_SECONDS = 30.0
FRAME_SECONDS = 1.0 / 60.0


def callback_name(callback_id):
    """Resolve a callback id to its struct's class name, or None if unknown.

    CALLBACK_REGISTRY is the same id->struct map the dispatch pump routes
    by, so this name matches exactly what run_frame() decoded the payload
    into.
    """
    cls = steam.CALLBACK_REGISTRY.get(callback_id)
    return cls.__name__ if cls is not None else None


def main():
    # Load + init, exactly as hello_steam.py does. (Kept terse here; that
    # file is the one with the friendly per-failure hints.)
    try:
        steam.load_steam_api()
    except steam.SteamLibraryNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    err = steam.SteamErrMsg()
    if steam.SteamAPI_InitFlat(err) != steam.k_ESteamAPIInitResult_OK:
        print(
            "Steam init failed: "
            + err.value.decode("utf-8", "replace").strip()
            + "\nIs the Steam client running and logged in, with "
            "steam_appid.txt (480) in this directory?",
            file=sys.stderr,
        )
        return 1

    # Opt into manual dispatch (once), then grab the pipe the pump runs on.
    steam.SteamAPI_ManualDispatch_Init()
    pipe = steam.SteamAPI_GetHSteamPipe()

    friends = steam.SteamAPI_SteamFriends_v018()
    persona = steam.SteamAPI_ISteamFriends_GetPersonaName(friends)
    print(f"Connected as {persona}. Pumping callbacks for {int(WATCH_SECONDS)} seconds...")
    print("(Open your friends list or the Steam overlay to generate some traffic.)\n")

    total = 0
    start = time.monotonic()
    # The loop a game runs every frame: pump once, do your per-frame work,
    # sleep until the next frame. run_frame() hands back this frame's
    # events as a plain list of (callback_id, payload) tuples.
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= WATCH_SECONDS:
            break

        for callback_id, payload in steam.run_frame(pipe):
            total += 1
            stamp = f"[t+{elapsed:05.2f}]"
            name = callback_name(callback_id)
            if name is not None:
                # A callback we have a struct for; payload is that struct.
                print(f"{stamp} id={callback_id} {name}")
            else:
                # Unknown id (or a size that disagreed with our struct):
                # the pump hands back raw bytes and has already freed the
                # callback slot. Nothing is lost; we just can't name it.
                print(
                    f"{stamp} id={callback_id} unknown, delivered as "
                    f"{len(payload)} raw bytes, freed"
                )

        time.sleep(FRAME_SECONDS)

    # Always shut down cleanly so the client releases our handles.
    steam.SteamAPI_Shutdown()
    print(f"\n{total} callbacks in {int(WATCH_SECONDS)}s, clean shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
