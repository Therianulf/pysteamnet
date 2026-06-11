"""pysteamnet -- a faithful, pure-ctypes Python mapping of the Steamworks flat C API.

No compiled shim, no C++, no build step, zero runtime dependencies:
Python talks directly to Valve's own shipped binary through ctypes.
Every function here keeps its exact flat-C name -- with Valve's docs
open you need zero translation. Pinned to Steamworks SDK v1.64.

The five-minute tour (a complete program):

    import time
    import pysteamnet as steam

    steam.load_steam_api()                 # find + load Valve's library
    err = steam.SteamErrMsg()
    if steam.SteamAPI_InitFlat(err) != steam.k_ESteamAPIInitResult_OK:
        raise SystemExit(err.value.decode("utf-8", "replace"))
    steam.SteamAPI_ManualDispatch_Init()   # opt into poll-style callbacks
    pipe = steam.SteamAPI_GetHSteamPipe()

    friends = steam.SteamAPI_SteamFriends_v018()
    print("Hello,", steam.SteamAPI_ISteamFriends_GetPersonaName(friends))

    for _ in range(60):                    # pump for a second
        for callback_id, payload in steam.run_frame(pipe):
            print("callback", callback_id, payload)
        time.sleep(1 / 60)

    steam.SteamAPI_Shutdown()

What lives where (all re-exported flat here, mirroring Valve's single
flat header):

    _loader.py     finding/loading the binary; load_steam_api()
    _bindings.py   every SteamAPI_* function, with verbose docstrings
    _dispatch.py   run_frame() / take_call_result() -- the callback pump
    _structs.py    callback structs (LobbyCreated_t, ...), identities
    _constants.py  Valve's enums and k_* constants
    _guards.py     the friendly preflight checks (internal)

The main names with no C equivalent -- the necessary Python plumbing:
load_steam_api (the ctypes bootstrap), run_frame / take_call_result
(the manual-dispatch loop as data), and ReceivedMessage (the safe copy
ReceiveMessagesOnChannel returns), plus a few supporting exports of the
same character (SteamLibraryNotFoundError, library_filename, the
FLAT_SIGNATURES / CALLBACK_REGISTRY introspection tables). Everything
else is Valve's API, name for name.
"""

# The flat namespace: every public symbol of the submodules is
# re-exported here so call sites read `pysteamnet.SteamAPI_...`, just
# as C reads `SteamAPI_...` out of one flat header.
from ._loader import (  # noqa: F401
    SteamLibraryNotFoundError,
    library_filename,
)
from ._bindings import *      # noqa: F401,F403  the SteamAPI_* functions
from ._bindings import (      # noqa: F401  (names * skips: underscore-free explicits)
    FLAT_SIGNATURES,
    ReceivedMessage,
    load_steam_api,
)
from ._dispatch import (  # noqa: F401
    run_frame,
    take_call_result,
)
from ._structs import (  # noqa: F401
    CALLBACK_REGISTRY,
    CallbackMsg_t,
    GameLobbyJoinRequested_t,
    LobbyChatMsg_t,
    LobbyChatUpdate_t,
    LobbyCreated_t,
    LobbyDataUpdate_t,
    LobbyEnter_t,
    LobbyInvite_t,
    LobbyMatchList_t,
    PersonaStateChange_t,
    SteamAPICallCompleted_t,
    SteamErrMsg,
    SteamNetConnectionInfo_t,
    SteamNetworkingIdentity,
    SteamNetworkingMessage_t,
    SteamNetworkingMessagesSessionFailed_t,
    SteamNetworkingMessagesSessionRequest_t,
)
from ._constants import *  # noqa: F401,F403  enums + k_* constants
