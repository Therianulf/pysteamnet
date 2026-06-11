#!/usr/bin/env python3
"""hello_steam.py -- the M0 smoke test: prove pysteamnet can talk to Steam.

This is the smallest end-to-end program in the project. It loads Valve's
shipped Steam library, connects to the running Steam client, and prints a
handful of facts about you and the running app:

    * your Steam persona (display) name
    * your 64-bit SteamID (the address peers will message you at)
    * the AppID we are running as (expected: 480, Valve's Spacewar test app)
    * whether we are running on a Steam Deck

If you can see your own name printed, the whole pure-ctypes stack works on
this machine: the library was found, ctypes loaded it, the flat C symbols
resolved, init succeeded, and a real call round-tripped to the client.

------------------------------------------------------------------------
PREREQUISITES
------------------------------------------------------------------------
1. The Steam client must be installed, RUNNING, and LOGGED IN. Init talks
   to that client process; there is nothing to talk to without it.

2. A file named  steam_appid.txt  containing exactly  480  must sit in the
   directory you run this from. It is gitignored, so create it once:
       echo 480 > steam_appid.txt
   During
   development this tells Steam which app we are, so we don't need a real
   AppID or a Steam launch. Shipped games drop this file and launch
   through Steam instead.

3. Valve's Steam library (libsteam_api.dylib / .so / steam_api64.dll) must
   be findable. It is NEVER committed to this repo -- download the
   Steamworks SDK (free, https://partner.steamgames.com/doc/sdk) and either
   drop the binary next to this script / in the cwd, or point at it with
   the PYSTEAMNET_LIBSTEAM_API environment variable. On this machine:

       export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx

------------------------------------------------------------------------
HOW TO RUN (from the repo root, where steam_appid.txt lives)
------------------------------------------------------------------------
    env PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx \
        python examples/hello_steam.py

------------------------------------------------------------------------
WHAT YOU SHOULD SEE
------------------------------------------------------------------------
Something like:

    Loading Valve's Steam library...
    Connecting to the Steam client...
    Connected.

    persona name : YourName
    SteamID64    : 76561198000000000
    AppID        : 480  (Spacewar, the public test app -- as expected)
    Steam Deck   : no

    Paste this to a friend so they can message you:
        your SteamID64 is 76561198000000000

That last line is what examples/messages_pingpong.py needs from each side.

------------------------------------------------------------------------
EXIT CODES
------------------------------------------------------------------------
    0  success -- everything above printed
    1  failure -- the library wasn't found, or init failed (the message
       explains which, and what to do about it)
"""

import sys

import pysteamnet as steam


# Init can fail for a few distinct reasons, and the fix differs for each.
# We map Valve's ESteamAPIInitResult codes to a plain-language hint so a
# failure tells you what to actually do, not just that something broke.
INIT_HINTS = {
    steam.k_ESteamAPIInitResult_NoSteamClient: (
        "Steam couldn't find a client to talk to. Is the Steam client "
        "running and logged in on this machine?"
    ),
    steam.k_ESteamAPIInitResult_VersionMismatch: (
        "The Steam client is older than this SDK expects. Update the "
        "Steam client (let it apply its pending update) and try again."
    ),
    steam.k_ESteamAPIInitResult_FailedGeneric: (
        "Generic init failure. Check that steam_appid.txt (containing 480) "
        "is in the directory you ran this from, and read the error text "
        "above for the specific reason."
    ),
}


def main():
    # Step 1: find and load Valve's library. This is the one verb in
    # pysteamnet that has no C equivalent -- the ctypes bootstrap. It uses
    # the documented search order (explicit path -> PYSTEAMNET_LIBSTEAM_API
    # -> package dir -> cwd) and raises a clear, location-listing error if
    # the binary isn't anywhere it looked.
    print("Loading Valve's Steam library...")
    try:
        steam.load_steam_api()
    except steam.SteamLibraryNotFoundError as exc:
        # The exception message already lists every path it tried.
        print(exc, file=sys.stderr)
        return 1

    # Step 2: connect to the running Steam client. We pass a SteamErrMsg
    # buffer so that on failure Steam writes a human-readable reason into
    # it -- worth printing alongside our own hint.
    print("Connecting to the Steam client...")
    err = steam.SteamErrMsg()
    result = steam.SteamAPI_InitFlat(err)
    if result != steam.k_ESteamAPIInitResult_OK:
        reason = err.value.decode("utf-8", "replace").strip()
        print(f"Steam init failed (result {int(result)}).", file=sys.stderr)
        if reason:
            print(f"  Steam says: {reason}", file=sys.stderr)
        hint = INIT_HINTS.get(result)
        if hint:
            print(f"  {hint}", file=sys.stderr)
        return 1
    print("Connected.\n")

    # Step 3: opt into manual dispatch. We don't pump callbacks in this
    # tiny example, but Init() is the once-per-process call that belongs
    # right after a successful InitFlat -- doing it here keeps the
    # canonical startup sequence visible.
    steam.SteamAPI_ManualDispatch_Init()

    # Step 4: ask Steam a few questions through the versioned interface
    # accessors. Each accessor returns an opaque interface pointer that we
    # pass back as the first argument of every call on that interface --
    # exactly as the flat C API does.
    friends = steam.SteamAPI_SteamFriends_v018()
    user = steam.SteamAPI_SteamUser_v023()
    utils = steam.SteamAPI_SteamUtils_v010()

    persona = steam.SteamAPI_ISteamFriends_GetPersonaName(friends)
    steamid64 = steam.SteamAPI_ISteamUser_GetSteamID(user)
    app_id = steam.SteamAPI_ISteamUtils_GetAppID(utils)
    on_deck = steam.SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck(utils)

    print(f"persona name : {persona}")
    print(f"SteamID64    : {steamid64}")
    if app_id == 480:
        print(f"AppID        : {app_id}  (Spacewar, the public test app -- as expected)")
    else:
        print(f"AppID        : {app_id}  (expected 480 -- check steam_appid.txt)")
    print(f"Steam Deck   : {'yes' if on_deck else 'no'}")

    # The line a friend needs: messages_pingpong addresses you by this id.
    print("\nPaste this to a friend so they can message you:")
    print(f"    your SteamID64 is {steamid64}")

    # Step 5: always shut down cleanly so the client releases our handles.
    steam.SteamAPI_Shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
