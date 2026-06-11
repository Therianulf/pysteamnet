"""The flat C API, mirrored function-for-function.

Every public function in this module has EXACTLY the name of a symbol
exported by Valve's steam_api library (steam_api_flat.h, SDK v1.64) --
a reader with Valve's docs open needs zero translation. Each function:

  1. runs the friendly preflight guards (_guards.py),
  2. calls the C export of the same name through ctypes,
  3. converts C-isms at the edge (bytes <-> str for text, IntEnum for
     enum returns) and nothing more.

FLAT_SIGNATURES below declares argtypes/restype for every symbol we
touch; bind_signatures() stamps them onto the loaded library so ctypes
itself rejects wrong argument types -- the runtime equivalent of C's
compile-time checking. The table is cross-checked against Valve's own
steam_api.json in the test suite.

Interface pointers: the C flat API passes `ISteamWhatever* self` as the
first argument of every interface call, and so do we. Get the pointer
from the versioned accessor, exactly like C:

    mm = pysteamnet.SteamAPI_SteamMatchmaking_v009()
    pysteamnet.SteamAPI_ISteamMatchmaking_CreateLobby(mm, ...)

The pointer is an opaque token (c_void_p) -- never dereferenced in
Python.

Two functions bend pure fidelity, both toward memory safety, both with
the real C signature documented in their docstring:
ReceiveMessagesOnChannel (owns the message release) and out-parameter
functions like GetLobbyChatEntry (out-params become return values, the
standard Python idiom for C out-params).
"""

import collections
import ctypes
from ctypes import POINTER, byref, c_bool, c_char_p, c_int, c_int32, c_uint32, c_uint64, c_void_p

from . import _guards
from ._loader import get_lib
from ._constants import (
    ELobbyComparison,
    ELobbyType,
    EResult,
    ESteamAPIInitResult,
    ESteamNetworkingConnectionState,
    _ALL_SEND_FLAG_BITS,
    k_cbMaxSteamNetworkingSocketsMessageSizeSend,
    k_nMaxLobbyKeyLength,
)
from ._structs import (
    CallbackMsg_t,
    SteamNetConnectionInfo_t,
    SteamNetworkingIdentity,
    SteamNetworkingMessage_t,
)

# ---------------------------------------------------------------------------
# argtypes/restype for every C symbol we use. None restype == C void.
# HSteamPipe/HSteamUser are int32; SteamAPICall_t and all SteamIDs are
# uint64; enums are c_int (C ints); interface pointers are c_void_p.
# ---------------------------------------------------------------------------

FLAT_SIGNATURES = {
    # --- init / shutdown / process-level (steam_api.h) ---
    "SteamAPI_InitFlat": ([c_char_p], c_int),
    "SteamAPI_Shutdown": ([], None),
    "SteamAPI_IsSteamRunning": ([], c_bool),
    "SteamAPI_RestartAppIfNecessary": ([c_uint32], c_bool),
    "SteamAPI_GetHSteamPipe": ([], c_int32),
    "SteamAPI_GetHSteamUser": ([], c_int32),

    # --- manual callback dispatch (steam_api.h:210-225) ---
    "SteamAPI_ManualDispatch_Init": ([], None),
    "SteamAPI_ManualDispatch_RunFrame": ([c_int32], None),
    "SteamAPI_ManualDispatch_GetNextCallback": ([c_int32, POINTER(CallbackMsg_t)], c_bool),
    "SteamAPI_ManualDispatch_FreeLastCallback": ([c_int32], None),
    "SteamAPI_ManualDispatch_GetAPICallResult":
        ([c_int32, c_uint64, c_void_p, c_int, c_int, POINTER(c_bool)], c_bool),

    # --- versioned interface accessors (steam_api_flat.h) ---
    "SteamAPI_SteamUser_v023": ([], c_void_p),
    "SteamAPI_SteamFriends_v018": ([], c_void_p),
    "SteamAPI_SteamUtils_v010": ([], c_void_p),
    "SteamAPI_SteamMatchmaking_v009": ([], c_void_p),
    "SteamAPI_SteamNetworkingMessages_SteamAPI_v002": ([], c_void_p),

    # --- ISteamUser ---
    "SteamAPI_ISteamUser_BLoggedOn": ([c_void_p], c_bool),
    "SteamAPI_ISteamUser_GetSteamID": ([c_void_p], c_uint64),

    # --- ISteamFriends ---
    "SteamAPI_ISteamFriends_GetPersonaName": ([c_void_p], c_char_p),
    "SteamAPI_ISteamFriends_GetFriendPersonaName": ([c_void_p, c_uint64], c_char_p),
    "SteamAPI_ISteamFriends_SetRichPresence": ([c_void_p, c_char_p, c_char_p], c_bool),
    "SteamAPI_ISteamFriends_ClearRichPresence": ([c_void_p], None),
    "SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog": ([c_void_p, c_uint64], None),

    # --- ISteamUtils ---
    "SteamAPI_ISteamUtils_GetAppID": ([c_void_p], c_uint32),
    "SteamAPI_ISteamUtils_IsOverlayEnabled": ([c_void_p], c_bool),
    "SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck": ([c_void_p], c_bool),

    # --- ISteamMatchmaking ---
    "SteamAPI_ISteamMatchmaking_RequestLobbyList": ([c_void_p], c_uint64),
    "SteamAPI_ISteamMatchmaking_AddRequestLobbyListStringFilter":
        ([c_void_p, c_char_p, c_char_p, c_int], None),
    "SteamAPI_ISteamMatchmaking_AddRequestLobbyListNumericalFilter":
        ([c_void_p, c_char_p, c_int, c_int], None),
    "SteamAPI_ISteamMatchmaking_AddRequestLobbyListResultCountFilter": ([c_void_p, c_int], None),
    "SteamAPI_ISteamMatchmaking_GetLobbyByIndex": ([c_void_p, c_int], c_uint64),
    "SteamAPI_ISteamMatchmaking_CreateLobby": ([c_void_p, c_int, c_int], c_uint64),
    "SteamAPI_ISteamMatchmaking_JoinLobby": ([c_void_p, c_uint64], c_uint64),
    "SteamAPI_ISteamMatchmaking_LeaveLobby": ([c_void_p, c_uint64], None),
    "SteamAPI_ISteamMatchmaking_InviteUserToLobby": ([c_void_p, c_uint64, c_uint64], c_bool),
    "SteamAPI_ISteamMatchmaking_GetNumLobbyMembers": ([c_void_p, c_uint64], c_int),
    "SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex": ([c_void_p, c_uint64, c_int], c_uint64),
    "SteamAPI_ISteamMatchmaking_GetLobbyData": ([c_void_p, c_uint64, c_char_p], c_char_p),
    "SteamAPI_ISteamMatchmaking_SetLobbyData": ([c_void_p, c_uint64, c_char_p, c_char_p], c_bool),
    "SteamAPI_ISteamMatchmaking_GetLobbyMemberData":
        ([c_void_p, c_uint64, c_uint64, c_char_p], c_char_p),
    "SteamAPI_ISteamMatchmaking_SetLobbyMemberData":
        ([c_void_p, c_uint64, c_char_p, c_char_p], None),
    "SteamAPI_ISteamMatchmaking_SendLobbyChatMsg": ([c_void_p, c_uint64, c_char_p, c_int], c_bool),
    "SteamAPI_ISteamMatchmaking_GetLobbyChatEntry":
        ([c_void_p, c_uint64, c_int, POINTER(c_uint64), c_char_p, c_int, POINTER(c_int32)], c_int),
    "SteamAPI_ISteamMatchmaking_SetLobbyMemberLimit": ([c_void_p, c_uint64, c_int], c_bool),
    "SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit": ([c_void_p, c_uint64], c_int),
    "SteamAPI_ISteamMatchmaking_SetLobbyJoinable": ([c_void_p, c_uint64, c_bool], c_bool),
    "SteamAPI_ISteamMatchmaking_GetLobbyOwner": ([c_void_p, c_uint64], c_uint64),

    # --- ISteamNetworkingMessages ---
    "SteamAPI_ISteamNetworkingMessages_SendMessageToUser":
        ([c_void_p, POINTER(SteamNetworkingIdentity), c_char_p, c_uint32, c_int, c_int], c_int),
    "SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel":
        ([c_void_p, c_int, POINTER(POINTER(SteamNetworkingMessage_t)), c_int], c_int),
    "SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser":
        ([c_void_p, POINTER(SteamNetworkingIdentity)], c_bool),
    "SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser":
        ([c_void_p, POINTER(SteamNetworkingIdentity)], c_bool),
    "SteamAPI_ISteamNetworkingMessages_CloseChannelWithUser":
        ([c_void_p, POINTER(SteamNetworkingIdentity), c_int], c_bool),
    "SteamAPI_ISteamNetworkingMessages_GetSessionConnectionInfo":
        ([c_void_p, POINTER(SteamNetworkingIdentity), POINTER(SteamNetConnectionInfo_t), c_void_p],
         c_int),

    # --- SteamNetworkingIdentity flat helpers ---
    "SteamAPI_SteamNetworkingIdentity_Clear": ([POINTER(SteamNetworkingIdentity)], None),
    "SteamAPI_SteamNetworkingIdentity_SetSteamID64":
        ([POINTER(SteamNetworkingIdentity), c_uint64], None),
    "SteamAPI_SteamNetworkingIdentity_GetSteamID64":
        ([POINTER(SteamNetworkingIdentity)], c_uint64),

    # --- SteamNetworkingMessage_t release ---
    "SteamAPI_SteamNetworkingMessage_t_Release": ([POINTER(SteamNetworkingMessage_t)], None),
}

# What `from pysteamnet import *` and the package namespace expose from
# this module: every flat symbol we bind (each has a same-named wrapper
# below) plus the few binding-layer names.
__all__ = list(FLAT_SIGNATURES) + [
    "FLAT_SIGNATURES",
    "ReceivedMessage",
    "bind_signatures",
    "load_steam_api",
]

_signatures_bound = False


def bind_signatures(lib):
    """Stamp argtypes/restype from FLAT_SIGNATURES onto the loaded library.

    This is what makes ctypes enforce C-equivalent typing on every call.
    Idempotent; called once by load_steam_api(). Raises AttributeError
    if the library is missing an expected export (which would mean an
    SDK/binary mismatch -- we pin SDK v1.64).
    """
    global _signatures_bound
    for name, (argtypes, restype) in FLAT_SIGNATURES.items():
        fn = getattr(lib, name)
        fn.argtypes = argtypes
        fn.restype = restype
    _signatures_bound = True


def load_steam_api(path=None):
    """Locate, load, and type-check Valve's steam_api library. Call once.

    The one verb pysteamnet adds that has no Valve equivalent -- it is
    the ctypes bootstrap. Everything else in this package mirrors a
    flat C symbol name exactly.

    Search order and per-OS filenames are documented on
    _loader.load_library. After this returns, call SteamAPI_InitFlat.
    """
    from . import _loader
    lib = _loader.load_library(path)
    if not _signatures_bound:
        bind_signatures(lib)
    return lib


def _to_enum(enum_cls, value):
    """Wrap an int return in Valve's IntEnum; pass unknown values through.

    (A newer Steam client may return values this SDK doesn't know;
    hiding them would be worse than returning the raw int.)
    """
    try:
        return enum_cls(value)
    except ValueError:
        return value


def _check_identity(name, value):
    """Require a SteamNetworkingIdentity struct, with the recipe to make one."""
    if not isinstance(value, SteamNetworkingIdentity):
        raise TypeError(
            f"{name} must be a pysteamnet.SteamNetworkingIdentity, got "
            f"{type(value).__name__}. Build one:\n"
            f"    ident = pysteamnet.SteamNetworkingIdentity()\n"
            f"    pysteamnet.SteamAPI_SteamNetworkingIdentity_SetSteamID64(ident, steamid64)"
        )


# ===========================================================================
# Init / shutdown / process-level
# ===========================================================================

def SteamAPI_InitFlat(pOutErrMsg=None):
    """Connect to the running Steam client. The first Steam call you make.

    C (steam_api.h:104):
        ESteamAPIInitResult SteamAPI_InitFlat( SteamErrMsg *pOutErrMsg );

    This is the exported init symbol -- the SteamAPI_Init/InitEx seen in
    Valve's C++ examples are header-inline wrappers that do not exist in
    the binary.

    Parameters:
        pOutErrMsg: None, or a pysteamnet.SteamErrMsg() buffer
            (char[1024]) that receives a human-readable reason on
            failure.

    Returns:
        ESteamAPIInitResult. 0 (k_ESteamAPIInitResult_OK) on success.
        2 (NoSteamClient) usually means Steam isn't running or you're
        not logged in; during development also check that a
        steam_appid.txt containing 480 sits in the working directory.

    Example:
        err = pysteamnet.SteamErrMsg()
        if pysteamnet.SteamAPI_InitFlat(err) != pysteamnet.k_ESteamAPIInitResult_OK:
            raise RuntimeError(err.value.decode("utf-8", "replace"))
    """
    lib = get_lib()
    if pOutErrMsg is not None and not (
        isinstance(pOutErrMsg, ctypes.Array) and ctypes.sizeof(pOutErrMsg) >= 1024
    ):
        raise TypeError(
            "pOutErrMsg must be None or a pysteamnet.SteamErrMsg() buffer "
            "(ctypes char array of at least 1024 bytes)."
        )
    return _to_enum(ESteamAPIInitResult, lib.SteamAPI_InitFlat(pOutErrMsg))


def SteamAPI_Shutdown():
    """Disconnect from Steam. Call once when the program exits.

    C (steam_api.h:107): void SteamAPI_Shutdown();
    """
    get_lib().SteamAPI_Shutdown()


def SteamAPI_IsSteamRunning():
    """True if a Steam client process is running on this machine.

    C (steam_api.h:139): bool SteamAPI_IsSteamRunning();
    """
    return get_lib().SteamAPI_IsSteamRunning()


def SteamAPI_RestartAppIfNecessary(unOwnAppID):
    """If launched outside Steam, relaunch through Steam and return True.

    C (steam_api.h:119):
        bool SteamAPI_RestartAppIfNecessary( uint32 unOwnAppID );

    Shipped builds call this before init and exit immediately if it
    returns True. Development against AppID 480 with a steam_appid.txt
    skips the relaunch (the file makes this return False).
    """
    lib = get_lib()
    _guards.check_uint("unOwnAppID", unOwnAppID, bits=32)
    return lib.SteamAPI_RestartAppIfNecessary(unOwnAppID)


def SteamAPI_GetHSteamPipe():
    """Return the communication pipe handle the dispatch pump runs on.

    C (steam_api_internal.h:17): HSteamPipe SteamAPI_GetHSteamPipe();
    Valid after SteamAPI_InitFlat succeeds; 0 means no pipe.
    """
    return get_lib().SteamAPI_GetHSteamPipe()


def SteamAPI_GetHSteamUser():
    """Return the handle of the logged-in Steam user.

    C (steam_api_internal.h:18): HSteamUser SteamAPI_GetHSteamUser();
    """
    return get_lib().SteamAPI_GetHSteamUser()


# ===========================================================================
# Manual callback dispatch -- the raw C surface.
# Most programs should call pysteamnet.run_frame() (in _dispatch.py),
# which drives these five in Valve's required order. They are exported
# verbatim so the pump has no private magic.
# ===========================================================================

def SteamAPI_ManualDispatch_Init():
    """Opt this process into manual callback dispatch. Call once after init.

    C (steam_api.h:210): void SteamAPI_ManualDispatch_Init();
    Manual dispatch exists precisely for non-C++ bindings like this one:
    no Steam thread ever calls into Python; we poll instead.
    """
    get_lib().SteamAPI_ManualDispatch_Init()


def SteamAPI_ManualDispatch_RunFrame(hSteamPipe):
    """Let Steam do its per-frame work for this pipe. Call every frame.

    C (steam_api.h:213):
        void SteamAPI_ManualDispatch_RunFrame( HSteamPipe hSteamPipe );
    """
    get_lib().SteamAPI_ManualDispatch_RunFrame(hSteamPipe)


def SteamAPI_ManualDispatch_GetNextCallback(hSteamPipe, pCallbackMsg):
    """Fetch the next pending callback into a CallbackMsg_t. True if one exists.

    C (steam_api.h:218):
        bool SteamAPI_ManualDispatch_GetNextCallback(
            HSteamPipe hSteamPipe, CallbackMsg_t *pCallbackMsg );

    If this returns True you MUST call FreeLastCallback after handling
    it -- even if you don't recognize the callback id.
    """
    return get_lib().SteamAPI_ManualDispatch_GetNextCallback(hSteamPipe, pCallbackMsg)


def SteamAPI_ManualDispatch_FreeLastCallback(hSteamPipe):
    """Release the callback returned by the last GetNextCallback. ALWAYS call.

    C (steam_api.h:221):
        void SteamAPI_ManualDispatch_FreeLastCallback( HSteamPipe hSteamPipe );
    """
    get_lib().SteamAPI_ManualDispatch_FreeLastCallback(hSteamPipe)


def SteamAPI_ManualDispatch_GetAPICallResult(
    hSteamPipe, hSteamAPICall, pCallback, cubCallback, iCallbackExpected, pbFailed
):
    """Copy a completed async call's result struct into a caller buffer.

    C (steam_api.h:225):
        bool SteamAPI_ManualDispatch_GetAPICallResult(
            HSteamPipe hSteamPipe, SteamAPICall_t hSteamAPICall,
            void *pCallback, int cubCallback, int iCallbackExpected,
            bool *pbFailed );

    Only meaningful while handling a SteamAPICallCompleted_t (id 703).
    cubCallback and iCallbackExpected come from the INNER fields of that
    struct (its m_cubParam / m_iCallback) -- note that the pseudocode
    comment in Valve's own steam_api.h is garbled here; trust this, the
    docs, and our pump tests.
    """
    return get_lib().SteamAPI_ManualDispatch_GetAPICallResult(
        hSteamPipe, hSteamAPICall, pCallback, cubCallback, iCallbackExpected, pbFailed
    )


# ===========================================================================
# Versioned interface accessors. The _vNNN suffix pins the interface
# version this SDK (v1.64) was built against; keeping it visible in
# every call site is deliberate (it is the compatibility contract).
# Each returns an opaque interface pointer, or None before init.
# ===========================================================================

def SteamAPI_SteamUser_v023():
    """Accessor for ISteamUser. C: ISteamUser* SteamAPI_SteamUser_v023();"""
    return get_lib().SteamAPI_SteamUser_v023()


def SteamAPI_SteamFriends_v018():
    """Accessor for ISteamFriends. C: ISteamFriends* SteamAPI_SteamFriends_v018();"""
    return get_lib().SteamAPI_SteamFriends_v018()


def SteamAPI_SteamUtils_v010():
    """Accessor for ISteamUtils. C: ISteamUtils* SteamAPI_SteamUtils_v010();"""
    return get_lib().SteamAPI_SteamUtils_v010()


def SteamAPI_SteamMatchmaking_v009():
    """Accessor for ISteamMatchmaking.

    C: ISteamMatchmaking* SteamAPI_SteamMatchmaking_v009();
    """
    return get_lib().SteamAPI_SteamMatchmaking_v009()


def SteamAPI_SteamNetworkingMessages_SteamAPI_v002():
    """Accessor for ISteamNetworkingMessages (note Valve's _SteamAPI_ infix).

    C: ISteamNetworkingMessages* SteamAPI_SteamNetworkingMessages_SteamAPI_v002();
    """
    return get_lib().SteamAPI_SteamNetworkingMessages_SteamAPI_v002()


# ===========================================================================
# ISteamUser -- https://partner.steamgames.com/doc/api/ISteamUser
# ===========================================================================

def SteamAPI_ISteamUser_BLoggedOn(self):
    """True if Steam has an active logged-in connection for this user.

    C: bool SteamAPI_ISteamUser_BLoggedOn( ISteamUser* self );
    """
    _guards.check_self_ptr("self (ISteamUser*)", self)
    return get_lib().SteamAPI_ISteamUser_BLoggedOn(self)


def SteamAPI_ISteamUser_GetSteamID(self):
    """Return our own 64-bit SteamID -- the address peers message us at.

    C: uint64_steamid SteamAPI_ISteamUser_GetSteamID( ISteamUser* self );
    Docs: https://partner.steamgames.com/doc/api/ISteamUser#GetSteamID

    Example:
        user = pysteamnet.SteamAPI_SteamUser_v023()
        my_id = pysteamnet.SteamAPI_ISteamUser_GetSteamID(user)
    """
    _guards.check_self_ptr("self (ISteamUser*)", self)
    return get_lib().SteamAPI_ISteamUser_GetSteamID(self)


# ===========================================================================
# ISteamFriends -- https://partner.steamgames.com/doc/api/ISteamFriends
# ===========================================================================

def SteamAPI_ISteamFriends_GetPersonaName(self):
    """Return the local user's display name as a str.

    C: const char* SteamAPI_ISteamFriends_GetPersonaName( ISteamFriends* self );
    Docs: https://partner.steamgames.com/doc/api/ISteamFriends#GetPersonaName

    The C return is a Steam-owned pointer valid only until the next API
    call; ctypes copies it to Python bytes at return, which we decode
    as UTF-8 -- so the str you get is safely yours.
    """
    _guards.check_self_ptr("self (ISteamFriends*)", self)
    raw = get_lib().SteamAPI_ISteamFriends_GetPersonaName(self)
    return (raw or b"").decode("utf-8", "replace")


def SteamAPI_ISteamFriends_GetFriendPersonaName(self, steamIDFriend):
    """Return a friend's display name ("" if unknown to this client).

    C: const char* SteamAPI_ISteamFriends_GetFriendPersonaName(
           ISteamFriends* self, uint64_steamid steamIDFriend );
    Docs: https://partner.steamgames.com/doc/api/ISteamFriends#GetFriendPersonaName

    Names are only known for friends and recent lobby/game peers. For
    strangers Steam returns "" until a PersonaStateChange_t (id 304)
    arrives with their info.
    """
    _guards.check_self_ptr("self (ISteamFriends*)", self)
    _guards.check_steamid("steamIDFriend", steamIDFriend)
    raw = get_lib().SteamAPI_ISteamFriends_GetFriendPersonaName(self, steamIDFriend)
    return (raw or b"").decode("utf-8", "replace")


def SteamAPI_ISteamFriends_SetRichPresence(self, pchKey, pchValue):
    """Publish a key/value visible on our profile to friends.

    C: bool SteamAPI_ISteamFriends_SetRichPresence(
           ISteamFriends* self, const char* pchKey, const char* pchValue );
    Docs: https://partner.steamgames.com/doc/api/ISteamFriends#SetRichPresence

    The magic keys "connect" and "status" power the friends-list
    "Join Game" button and status line. Pass value None (C NULL) or ""
    to clear a key. Returns False if the key/value exceeds Steam's
    limits.
    """
    _guards.check_self_ptr("self (ISteamFriends*)", self)
    _guards.check_str("pchKey", pchKey)
    if pchValue is not None:
        _guards.check_str("pchValue", pchValue)
    return get_lib().SteamAPI_ISteamFriends_SetRichPresence(
        self, pchKey.encode("utf-8"),
        None if pchValue is None else pchValue.encode("utf-8"),
    )


def SteamAPI_ISteamFriends_ClearRichPresence(self):
    """Remove all of our rich-presence keys.

    C: void SteamAPI_ISteamFriends_ClearRichPresence( ISteamFriends* self );
    """
    _guards.check_self_ptr("self (ISteamFriends*)", self)
    get_lib().SteamAPI_ISteamFriends_ClearRichPresence(self)


def SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog(self, steamIDLobby):
    """Open the Steam overlay's invite-friends dialog for a lobby.

    C: void SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog(
           ISteamFriends* self, uint64_steamid steamIDLobby );
    Docs: https://partner.steamgames.com/doc/api/ISteamFriends#ActivateGameOverlayInviteDialog

    Invited friends receive GameLobbyJoinRequested_t (id 333) when they
    accept. Requires the overlay (IsOverlayEnabled).
    """
    _guards.check_self_ptr("self (ISteamFriends*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    get_lib().SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog(self, steamIDLobby)


# ===========================================================================
# ISteamUtils -- https://partner.steamgames.com/doc/api/ISteamUtils
# ===========================================================================

def SteamAPI_ISteamUtils_GetAppID(self):
    """Return the AppID we're running as (480 in development).

    C: uint32 SteamAPI_ISteamUtils_GetAppID( ISteamUtils* self );
    """
    _guards.check_self_ptr("self (ISteamUtils*)", self)
    return get_lib().SteamAPI_ISteamUtils_GetAppID(self)


def SteamAPI_ISteamUtils_IsOverlayEnabled(self):
    """True if the Steam overlay is running in this process.

    C: bool SteamAPI_ISteamUtils_IsOverlayEnabled( ISteamUtils* self );
    Plain Python scripts usually return False here (the overlay injects
    into the game's renderer); invite dialogs then can't open.
    """
    _guards.check_self_ptr("self (ISteamUtils*)", self)
    return get_lib().SteamAPI_ISteamUtils_IsOverlayEnabled(self)


def SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck(self):
    """True when running on a Steam Deck.

    C: bool SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck( ISteamUtils* self );
    """
    _guards.check_self_ptr("self (ISteamUtils*)", self)
    return get_lib().SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck(self)


# ===========================================================================
# ISteamMatchmaking -- https://partner.steamgames.com/doc/api/ISteamMatchmaking
# Lobbies are Steam's pre-game meeting rooms: up to 250 members, shared
# key/value data, chat, and friend invites. All SteamIDs are plain ints.
# ===========================================================================

def SteamAPI_ISteamMatchmaking_RequestLobbyList(self):
    """Start an async search for public lobbies of this game.

    C: SteamAPICall_t SteamAPI_ISteamMatchmaking_RequestLobbyList(
           ISteamMatchmaking* self );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#RequestLobbyList

    Apply AddRequestLobbyList*Filter calls BEFORE this; they affect only
    the next search. Returns a SteamAPICall_t handle; the result is a
    LobbyMatchList_t (id 510) call-result -- pump run_frame() and either
    watch the returned events or poll take_call_result(handle). Then
    iterate GetLobbyByIndex(0..m_nLobbiesMatching-1).
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    return get_lib().SteamAPI_ISteamMatchmaking_RequestLobbyList(self)


def SteamAPI_ISteamMatchmaking_AddRequestLobbyListStringFilter(
    self, pchKeyToMatch, pchValueToMatch, eComparisonType
):
    """Filter the next lobby search by a string lobby-data value.

    C: void ...AddRequestLobbyListStringFilter( ISteamMatchmaking* self,
           const char* pchKeyToMatch, const char* pchValueToMatch,
           ELobbyComparison eComparisonType );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_str("pchKeyToMatch", pchKeyToMatch, max_len=k_nMaxLobbyKeyLength)
    _guards.check_str("pchValueToMatch", pchValueToMatch)
    _guards.check_enum("eComparisonType", eComparisonType, ELobbyComparison)
    get_lib().SteamAPI_ISteamMatchmaking_AddRequestLobbyListStringFilter(
        self, pchKeyToMatch.encode("utf-8"), pchValueToMatch.encode("utf-8"), eComparisonType
    )


def SteamAPI_ISteamMatchmaking_AddRequestLobbyListNumericalFilter(
    self, pchKeyToMatch, nValueToMatch, eComparisonType
):
    """Filter the next lobby search by a numeric lobby-data value.

    C: void ...AddRequestLobbyListNumericalFilter( ISteamMatchmaking* self,
           const char* pchKeyToMatch, int nValueToMatch,
           ELobbyComparison eComparisonType );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_str("pchKeyToMatch", pchKeyToMatch, max_len=k_nMaxLobbyKeyLength)
    _guards.check_int_range("nValueToMatch", nValueToMatch, -(2**31), 2**31 - 1)
    _guards.check_enum("eComparisonType", eComparisonType, ELobbyComparison)
    get_lib().SteamAPI_ISteamMatchmaking_AddRequestLobbyListNumericalFilter(
        self, pchKeyToMatch.encode("utf-8"), nValueToMatch, eComparisonType
    )


def SteamAPI_ISteamMatchmaking_AddRequestLobbyListResultCountFilter(self, cMaxResults):
    """Cap how many lobbies the next search returns (cheaper, faster).

    C: void ...AddRequestLobbyListResultCountFilter(
           ISteamMatchmaking* self, int cMaxResults );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_int_range("cMaxResults", cMaxResults, 1, 50)
    get_lib().SteamAPI_ISteamMatchmaking_AddRequestLobbyListResultCountFilter(self, cMaxResults)


def SteamAPI_ISteamMatchmaking_GetLobbyByIndex(self, iLobby):
    """Return the SteamID of result #iLobby from the last finished search.

    C: uint64_steamid SteamAPI_ISteamMatchmaking_GetLobbyByIndex(
           ISteamMatchmaking* self, int iLobby );
    Valid only after the LobbyMatchList_t result, for
    0 <= iLobby < m_nLobbiesMatching.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_int_range("iLobby", iLobby, 0, 2**31 - 1)
    return get_lib().SteamAPI_ISteamMatchmaking_GetLobbyByIndex(self, iLobby)


def SteamAPI_ISteamMatchmaking_CreateLobby(self, eLobbyType, cMaxMembers):
    """Ask Steam to create a lobby. The lobby arrives later, async.

    C: SteamAPICall_t SteamAPI_ISteamMatchmaking_CreateLobby(
           ISteamMatchmaking* self, ELobbyType eLobbyType, int cMaxMembers );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#CreateLobby

    Parameters:
        eLobbyType: an ELobbyType (k_ELobbyTypePrivate/FriendsOnly/
            Public/Invisible/PrivateUnique).
        cMaxMembers: max players including us, 1..250.

    Returns:
        SteamAPICall_t handle (int). Compare with k_uAPICallInvalid (0)
        for immediate failure. The real result is a LobbyCreated_t
        (id 513) call-result; on success we are already in the lobby
        and a LobbyEnter_t (504) broadcast follows.

    Example:
        mm = pysteamnet.SteamAPI_SteamMatchmaking_v009()
        call = pysteamnet.SteamAPI_ISteamMatchmaking_CreateLobby(
            mm, pysteamnet.k_ELobbyTypeFriendsOnly, 4)
        # ...pump run_frame() until take_call_result(call) returns.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_enum("eLobbyType", eLobbyType, ELobbyType)
    _guards.check_int_range("cMaxMembers", cMaxMembers, 1, 250)
    return get_lib().SteamAPI_ISteamMatchmaking_CreateLobby(self, eLobbyType, cMaxMembers)


def SteamAPI_ISteamMatchmaking_JoinLobby(self, steamIDLobby):
    """Ask to join an existing lobby. Result arrives async.

    C: SteamAPICall_t SteamAPI_ISteamMatchmaking_JoinLobby(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#JoinLobby

    Returns a SteamAPICall_t handle; the result is a LobbyEnter_t
    (id 504) -- check m_EChatRoomEnterResponse == 1 (success).
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    return get_lib().SteamAPI_ISteamMatchmaking_JoinLobby(self, steamIDLobby)


def SteamAPI_ISteamMatchmaking_LeaveLobby(self, steamIDLobby):
    """Leave a lobby. Instant, no callback. Other members see LobbyChatUpdate_t.

    C: void SteamAPI_ISteamMatchmaking_LeaveLobby(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    get_lib().SteamAPI_ISteamMatchmaking_LeaveLobby(self, steamIDLobby)


def SteamAPI_ISteamMatchmaking_InviteUserToLobby(self, steamIDLobby, steamIDInvitee):
    """Invite a user to a lobby we're in. They get LobbyInvite_t / a chat link.

    C: bool SteamAPI_ISteamMatchmaking_InviteUserToLobby(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           uint64_steamid steamIDInvitee );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#InviteUserToLobby

    If the invitee is in-game they receive LobbyInvite_t (id 503);
    accepting from the Steam UI delivers GameLobbyJoinRequested_t (333).
    Returns True if the invite was sent.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_steamid("steamIDInvitee", steamIDInvitee)
    return get_lib().SteamAPI_ISteamMatchmaking_InviteUserToLobby(
        self, steamIDLobby, steamIDInvitee
    )


def SteamAPI_ISteamMatchmaking_GetNumLobbyMembers(self, steamIDLobby):
    """How many users are in a lobby (must be in it, or have it from a search).

    C: int SteamAPI_ISteamMatchmaking_GetNumLobbyMembers(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    return get_lib().SteamAPI_ISteamMatchmaking_GetNumLobbyMembers(self, steamIDLobby)


def SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex(self, steamIDLobby, iMember):
    """Return member #iMember's SteamID (we must be in the lobby).

    C: uint64_steamid SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby, int iMember );
    Valid for 0 <= iMember < GetNumLobbyMembers(...).
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_int_range("iMember", iMember, 0, 2**31 - 1)
    return get_lib().SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex(
        self, steamIDLobby, iMember
    )


def SteamAPI_ISteamMatchmaking_GetLobbyData(self, steamIDLobby, pchKey):
    """Read a lobby's shared key/value data. Returns "" for missing keys.

    C: const char* SteamAPI_ISteamMatchmaking_GetLobbyData(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           const char* pchKey );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#GetLobbyData

    Lobby data is replicated to every member automatically (and to
    searchers via RequestLobbyList). The C return is Steam-owned and
    ephemeral; you get a safe Python str copy.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_str("pchKey", pchKey, max_len=k_nMaxLobbyKeyLength)
    raw = get_lib().SteamAPI_ISteamMatchmaking_GetLobbyData(
        self, steamIDLobby, pchKey.encode("utf-8")
    )
    return (raw or b"").decode("utf-8", "replace")


def SteamAPI_ISteamMatchmaking_SetLobbyData(self, steamIDLobby, pchKey, pchValue):
    """Set a lobby key/value (lobby owner only). Members get LobbyDataUpdate_t.

    C: bool SteamAPI_ISteamMatchmaking_SetLobbyData(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           const char* pchKey, const char* pchValue );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#SetLobbyData

    Keys are limited to 255 bytes. Returns True if the change was
    accepted locally.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_str("pchKey", pchKey, max_len=k_nMaxLobbyKeyLength)
    _guards.check_str("pchValue", pchValue)
    return get_lib().SteamAPI_ISteamMatchmaking_SetLobbyData(
        self, steamIDLobby, pchKey.encode("utf-8"), pchValue.encode("utf-8")
    )


def SteamAPI_ISteamMatchmaking_GetLobbyMemberData(self, steamIDLobby, steamIDUser, pchKey):
    """Read another member's per-member key/value data ("" if unset).

    C: const char* SteamAPI_ISteamMatchmaking_GetLobbyMemberData(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           uint64_steamid steamIDUser, const char* pchKey );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_steamid("steamIDUser", steamIDUser)
    _guards.check_str("pchKey", pchKey, max_len=k_nMaxLobbyKeyLength)
    raw = get_lib().SteamAPI_ISteamMatchmaking_GetLobbyMemberData(
        self, steamIDLobby, steamIDUser, pchKey.encode("utf-8")
    )
    return (raw or b"").decode("utf-8", "replace")


def SteamAPI_ISteamMatchmaking_SetLobbyMemberData(self, steamIDLobby, pchKey, pchValue):
    """Set OUR per-member key/value in this lobby (e.g. "ready": "1").

    C: void SteamAPI_ISteamMatchmaking_SetLobbyMemberData(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           const char* pchKey, const char* pchValue );
    Other members learn of it via LobbyDataUpdate_t with
    m_ulSteamIDMember == our id.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_str("pchKey", pchKey, max_len=k_nMaxLobbyKeyLength)
    _guards.check_str("pchValue", pchValue)
    get_lib().SteamAPI_ISteamMatchmaking_SetLobbyMemberData(
        self, steamIDLobby, pchKey.encode("utf-8"), pchValue.encode("utf-8")
    )


def SteamAPI_ISteamMatchmaking_SendLobbyChatMsg(self, steamIDLobby, pvMsgBody):
    """Broadcast a binary chat message to everyone in the lobby.

    C: bool SteamAPI_ISteamMatchmaking_SendLobbyChatMsg(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           const void* pvMsgBody, int cubMsgBody );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#SendLobbyChatMsg

    pvMsgBody is bytes; cubMsgBody is derived from len(pvMsgBody) (the
    one C parameter pysteamnet fills for you -- a length that disagrees
    with the buffer is the classic FFI bug). Receivers get
    LobbyChatMsg_t (id 507) and read it with GetLobbyChatEntry.
    Lobby chat is fine for setup traffic; gameplay traffic belongs on
    ISteamNetworkingMessages.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_bytes("pvMsgBody", pvMsgBody)
    body = bytes(pvMsgBody)
    return get_lib().SteamAPI_ISteamMatchmaking_SendLobbyChatMsg(
        self, steamIDLobby, body, len(body)
    )


def SteamAPI_ISteamMatchmaking_GetLobbyChatEntry(self, steamIDLobby, iChatID, cubData=4096):
    """Fetch chat entry #iChatID. Returns (data, sender_steamid, entry_type).

    C: int SteamAPI_ISteamMatchmaking_GetLobbyChatEntry(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           int iChatID, CSteamID* pSteamIDUser, void* pvData,
           int cubData, EChatEntryType* peChatEntryType );
    Docs: https://partner.steamgames.com/doc/api/ISteamMatchmaking#GetLobbyChatEntry

    The C out-parameters come back as a Python tuple instead:
        data        bytes -- the message body (C return value = its length)
        sender      int   -- SteamID of who sent it
        entry_type  int   -- EChatEntryType (1 == k_EChatEntryTypeChatMsg)

    iChatID comes from LobbyChatMsg_t.m_iChatID. cubData is the read
    buffer size (default 4096, Valve's documented chat maximum).
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_int_range("iChatID", iChatID, 0, 2**31 - 1)
    _guards.check_int_range("cubData", cubData, 1, 2**31 - 1)
    sender = c_uint64(0)
    entry_type = c_int32(0)
    buf = ctypes.create_string_buffer(cubData)
    n = get_lib().SteamAPI_ISteamMatchmaking_GetLobbyChatEntry(
        self, steamIDLobby, iChatID, byref(sender), buf, cubData, byref(entry_type)
    )
    return buf.raw[: max(n, 0)], sender.value, entry_type.value


def SteamAPI_ISteamMatchmaking_SetLobbyMemberLimit(self, steamIDLobby, cMaxMembers):
    """Change a lobby's member cap (owner only).

    C: bool SteamAPI_ISteamMatchmaking_SetLobbyMemberLimit(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby, int cMaxMembers );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    _guards.check_int_range("cMaxMembers", cMaxMembers, 1, 250)
    return get_lib().SteamAPI_ISteamMatchmaking_SetLobbyMemberLimit(
        self, steamIDLobby, cMaxMembers
    )


def SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit(self, steamIDLobby):
    """Return a lobby's member cap (0 if no limit is set).

    C: int SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby );
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    return get_lib().SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit(self, steamIDLobby)


def SteamAPI_ISteamMatchmaking_SetLobbyJoinable(self, steamIDLobby, bLobbyJoinable):
    """Allow or forbid new members (owner only). Lobbies start joinable.

    C: bool SteamAPI_ISteamMatchmaking_SetLobbyJoinable(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby,
           bool bLobbyJoinable );
    Typical use: lock the lobby when the match starts.
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    if not isinstance(bLobbyJoinable, bool):
        raise TypeError(
            f"bLobbyJoinable must be a bool, got {type(bLobbyJoinable).__name__}."
        )
    return get_lib().SteamAPI_ISteamMatchmaking_SetLobbyJoinable(
        self, steamIDLobby, bLobbyJoinable
    )


def SteamAPI_ISteamMatchmaking_GetLobbyOwner(self, steamIDLobby):
    """Return the lobby owner's SteamID (we must be in the lobby).

    C: uint64_steamid SteamAPI_ISteamMatchmaking_GetLobbyOwner(
           ISteamMatchmaking* self, uint64_steamid steamIDLobby );
    Steam migrates ownership automatically if the owner leaves; the
    owner is a good default for "who is the game host".
    """
    _guards.check_self_ptr("self (ISteamMatchmaking*)", self)
    _guards.check_steamid("steamIDLobby", steamIDLobby)
    return get_lib().SteamAPI_ISteamMatchmaking_GetLobbyOwner(self, steamIDLobby)


# ===========================================================================
# ISteamNetworkingMessages -- https://partner.steamgames.com/doc/api/ISteamNetworkingMessages
# The transport: UDP-style datagrams addressed by SteamID, with optional
# reliability, NAT punching and Valve relay fallback handled by Steam.
# ===========================================================================

ReceivedMessage = collections.namedtuple(
    "ReceivedMessage",
    ["sender_steamid64", "data", "channel", "flags", "message_number"],
)
ReceivedMessage.__doc__ = """One received message, copied out of Steam's buffers.

A plain-data snapshot of Valve's SteamNetworkingMessage_t, taken just
before the message was released back to Steam:

    sender_steamid64  int   -- m_identityPeer as a 64-bit SteamID
    data              bytes -- copy of m_pData[:m_cbSize]
    channel           int   -- m_nChannel
    flags             int   -- m_nFlags (only the Reliable bit=8 is
                               meaningful on receive)
    message_number    int   -- m_nMessageNumber (per-sender sequence)
"""


def SteamAPI_ISteamNetworkingMessages_SendMessageToUser(
    self, identityRemote, pubData, nSendFlags, nRemoteChannel
):
    """Send one datagram to a peer identified by SteamID.

    C (steam_api_flat.h:984):
        EResult SteamAPI_ISteamNetworkingMessages_SendMessageToUser(
            ISteamNetworkingMessages* self,
            const SteamNetworkingIdentity& identityRemote,
            const void* pubData, uint32 cubData,
            int nSendFlags, int nRemoteChannel );
    Docs: https://partner.steamgames.com/doc/api/ISteamNetworkingMessages#SendMessageToUser

    Parameters:
        identityRemote: a SteamNetworkingIdentity (build with
            SteamAPI_SteamNetworkingIdentity_SetSteamID64). Passed by
            reference to C, exactly as declared.
        pubData: bytes payload, max 512 KiB. cubData is derived from
            len(pubData) -- the one C parameter filled for you.
        nSendFlags: k_nSteamNetworkingSend_Reliable for ordered,
            guaranteed delivery; k_nSteamNetworkingSend_UnreliableNoNagle
            for lowest latency fire-and-forget.
        nRemoteChannel: app-defined lane; receiver must poll the same
            number in ReceiveMessagesOnChannel.

    Returns:
        EResult. k_EResultOK (1) means accepted for delivery. The first
        send to a new peer starts a session; their client must accept
        it (SteamNetworkingMessagesSessionRequest_t ->
        AcceptSessionWithUser) unless they message us first.
    """
    _guards.check_self_ptr("self (ISteamNetworkingMessages*)", self)
    _check_identity("identityRemote", identityRemote)
    _guards.check_bytes(
        "pubData", pubData, max_len=k_cbMaxSteamNetworkingSocketsMessageSizeSend
    )
    _guards.check_flags("nSendFlags", nSendFlags, _ALL_SEND_FLAG_BITS)
    _guards.check_int_range("nRemoteChannel", nRemoteChannel, 0, 2**31 - 1)
    data = bytes(pubData)
    return _to_enum(
        EResult,
        get_lib().SteamAPI_ISteamNetworkingMessages_SendMessageToUser(
            self, identityRemote, data, len(data), nSendFlags, nRemoteChannel
        ),
    )


def SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
    self, nLocalChannel, nMaxMessages=16
):
    """Drain pending messages on a channel. Returns a list of ReceivedMessage.

    C (steam_api_flat.h:985):
        int SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
            ISteamNetworkingMessages* self, int nLocalChannel,
            SteamNetworkingMessage_t** ppOutMessages, int nMaxMessages );
    Docs: https://partner.steamgames.com/doc/api/ISteamNetworkingMessages#ReceiveMessagesOnChannel

    This is the one deliberately-managed wrapper in pysteamnet: the C
    call hands back pointers that MUST each be released exactly once.
    Doing that by hand from Python is a use-after-free factory, so this
    wrapper allocates the pointer array, copies every payload into
    Python bytes, releases every message via Valve's
    SteamAPI_SteamNetworkingMessage_t_Release (in a finally), and
    returns plain data. Same information, no foreign memory in sight.

    Call every frame (after run_frame()) until it returns []. An empty
    list just means nothing arrived.
    """
    _guards.check_self_ptr("self (ISteamNetworkingMessages*)", self)
    _guards.check_int_range("nLocalChannel", nLocalChannel, 0, 2**31 - 1)
    _guards.check_int_range("nMaxMessages", nMaxMessages, 1, 8192)
    lib = get_lib()
    ptrs = (POINTER(SteamNetworkingMessage_t) * nMaxMessages)()
    n = lib.SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(
        self, nLocalChannel, ptrs, nMaxMessages
    )
    out = []
    try:
        for i in range(max(n, 0)):
            msg = ptrs[i].contents
            out.append(ReceivedMessage(
                sender_steamid64=lib.SteamAPI_SteamNetworkingIdentity_GetSteamID64(
                    byref(msg.m_identityPeer)
                ),
                data=ctypes.string_at(msg.m_pData, msg.m_cbSize),
                channel=msg.m_nChannel,
                flags=msg.m_nFlags,
                message_number=msg.m_nMessageNumber,
            ))
    finally:
        # Release EVERY message Steam handed us, exactly once, even if
        # copying one of them raised above -- a skipped release leaks
        # the message back in Steam's pool for the life of the process.
        for i in range(max(n, 0)):
            lib.SteamAPI_SteamNetworkingMessage_t_Release(ptrs[i])
    return out


def SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser(self, identityRemote):
    """Accept an incoming session so a new peer's messages get through.

    C: bool SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser(
           ISteamNetworkingMessages* self,
           const SteamNetworkingIdentity& identityRemote );
    Docs: https://partner.steamgames.com/doc/api/ISteamNetworkingMessages#AcceptSessionWithUser

    Call in response to SteamNetworkingMessagesSessionRequest_t
    (id 1251), passing the callback's m_identityRemote. Sending TO a
    peer accepts their session implicitly.
    """
    _guards.check_self_ptr("self (ISteamNetworkingMessages*)", self)
    _check_identity("identityRemote", identityRemote)
    return get_lib().SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser(
        self, identityRemote
    )


def SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser(self, identityRemote):
    """Tear down the session with a peer (all channels, frees resources).

    C: bool SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser(
           ISteamNetworkingMessages* self,
           const SteamNetworkingIdentity& identityRemote );
    The peer gets no notification (UDP-style); unsent messages are
    dropped. Call when done talking to someone.
    """
    _guards.check_self_ptr("self (ISteamNetworkingMessages*)", self)
    _check_identity("identityRemote", identityRemote)
    return get_lib().SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser(
        self, identityRemote
    )


def SteamAPI_ISteamNetworkingMessages_CloseChannelWithUser(self, identityRemote, nLocalChannel):
    """Close one channel to a peer; the session ends when no channels remain.

    C: bool SteamAPI_ISteamNetworkingMessages_CloseChannelWithUser(
           ISteamNetworkingMessages* self,
           const SteamNetworkingIdentity& identityRemote, int nLocalChannel );
    """
    _guards.check_self_ptr("self (ISteamNetworkingMessages*)", self)
    _check_identity("identityRemote", identityRemote)
    _guards.check_int_range("nLocalChannel", nLocalChannel, 0, 2**31 - 1)
    return get_lib().SteamAPI_ISteamNetworkingMessages_CloseChannelWithUser(
        self, identityRemote, nLocalChannel
    )


def SteamAPI_ISteamNetworkingMessages_GetSessionConnectionInfo(
    self, identityRemote, pConnectionInfo=None
):
    """Inspect the state of our session with a peer.

    C: ESteamNetworkingConnectionState
       SteamAPI_ISteamNetworkingMessages_GetSessionConnectionInfo(
           ISteamNetworkingMessages* self,
           const SteamNetworkingIdentity& identityRemote,
           SteamNetConnectionInfo_t* pConnectionInfo,
           SteamNetConnectionRealTimeStatus_t* pQuickStatus );

    Pass a SteamNetConnectionInfo_t to have it filled in, or leave None
    to get just the state. (The pQuickStatus out-param is not bound in
    this slice and is always passed as NULL.)

    Returns ESteamNetworkingConnectionState (3 == Connected; 0 == None,
    i.e. no session).
    """
    _guards.check_self_ptr("self (ISteamNetworkingMessages*)", self)
    _check_identity("identityRemote", identityRemote)
    if pConnectionInfo is not None and not isinstance(pConnectionInfo, SteamNetConnectionInfo_t):
        raise TypeError(
            "pConnectionInfo must be None or a pysteamnet.SteamNetConnectionInfo_t."
        )
    return _to_enum(
        ESteamNetworkingConnectionState,
        get_lib().SteamAPI_ISteamNetworkingMessages_GetSessionConnectionInfo(
            self, identityRemote, pConnectionInfo, None
        ),
    )


# ===========================================================================
# SteamNetworkingIdentity flat helpers -- Valve's own constructors for
# the identity struct, so the layout knowledge stays in Valve's code.
# ===========================================================================

def SteamAPI_SteamNetworkingIdentity_Clear(self):
    """Zero an identity (type becomes Invalid).

    C: void SteamAPI_SteamNetworkingIdentity_Clear( SteamNetworkingIdentity* self );
    """
    _check_identity("self", self)
    get_lib().SteamAPI_SteamNetworkingIdentity_Clear(self)


def SteamAPI_SteamNetworkingIdentity_SetSteamID64(self, steamID):
    """Make an identity mean "the user with this 64-bit SteamID".

    C (steam_api_flat.h:1214):
        void SteamAPI_SteamNetworkingIdentity_SetSteamID64(
            SteamNetworkingIdentity* self, uint64 steamID );

    Example:
        ident = pysteamnet.SteamNetworkingIdentity()
        pysteamnet.SteamAPI_SteamNetworkingIdentity_SetSteamID64(ident, peer_id)
    """
    _check_identity("self", self)
    _guards.check_steamid("steamID", steamID)
    get_lib().SteamAPI_SteamNetworkingIdentity_SetSteamID64(self, steamID)


def SteamAPI_SteamNetworkingIdentity_GetSteamID64(self):
    """Read an identity's SteamID (0 if it isn't a SteamID identity).

    C: uint64 SteamAPI_SteamNetworkingIdentity_GetSteamID64(
           SteamNetworkingIdentity* self );
    """
    _check_identity("self", self)
    return get_lib().SteamAPI_SteamNetworkingIdentity_GetSteamID64(self)


def SteamAPI_SteamNetworkingMessage_t_Release(pMessage):
    """Release a raw SteamNetworkingMessage_t pointer back to Steam.

    C (steam_api_flat.h:1237):
        void SteamAPI_SteamNetworkingMessage_t_Release(
            SteamNetworkingMessage_t* self );

    Exported for completeness; pysteamnet's ReceiveMessagesOnChannel
    already releases everything it returns, so user code should never
    need this.
    """
    get_lib().SteamAPI_SteamNetworkingMessage_t_Release(pMessage)
