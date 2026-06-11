"""ctypes mirrors of the Steamworks structs this binding touches.

Every layout here was transcribed from the SDK v1.64 headers and is
locked down by size/offset assertions in the test suite. Getting these
wrong does not crash -- it silently corrupts fields -- so the packing
rules deserve a moment of attention:

PACKING (the single most important correctness rule in this file)

  Valve compiles callback structs under "#pragma pack" with a width
  that DEPENDS ON THE PLATFORM (steamclientpublic.h:1143-1160):

      macOS / Linux / FreeBSD  ->  pack(4)
      Windows                  ->  pack(8)

  ...EXCEPT for the SteamNetworking types, which carry their own
  pragmas and are the same on every platform:

      SteamNetworkingIPAddr, SteamNetworkingIdentity  -> pack(1)
        (steamnetworkingtypes.h:193-343)
      SteamNetworkingMessagesSessionRequest_t,
      SteamNetworkingMessagesSessionFailed_t    -> pack(1)
        (isteamnetworkingmessages.h:133-163)
      SteamNetworkingMessage_t                  -> natural alignment
        (steamnetworkingtypes.h:844, defined outside any pack region)
      SteamNetConnectionInfo_t                  -> defined under the
        platform pack(4)/pack(8) region (steamnetworkingtypes.h:673),
        but Valve laid it out with explicit padding so its layout is
        IDENTICAL under pack 1, 4, or 8 (696 bytes, same offsets --
        verified against a real C compiler). We declare it pack(1) so
        it embeds consistently inside the pack(1) SessionFailed_t.

  So _pack_ is set per struct, never globally.

CSteamID / CGameID are packed 64-bit values; the flat API already
collapses them to uint64, so they appear here as ctypes.c_uint64 and as
plain Python ints everywhere else.

Each callback struct keeps its k_iCallback as a class attribute, exactly
like the C++ "enum { k_iCallback = ... }". CALLBACK_REGISTRY at the
bottom maps id -> class for the dispatch pump.
"""

import ctypes
import sys

# The platform-dependent pack width for ordinary callback structs.
# Mirrors VALVE_CALLBACK_PACK_SMALL/LARGE: 4 on the POSIX family Steam
# supports, 8 on Windows.
PACK_VALVE_CALLBACK = 8 if sys.platform == "win32" else 4


# ---------------------------------------------------------------------------
# Manual-dispatch plumbing structs (steam_api_internal.h, isteamutils.h)
# ---------------------------------------------------------------------------

class CallbackMsg_t(ctypes.Structure):
    """One pending callback, as handed out by ManualDispatch_GetNextCallback.

    m_pubParam points at the callback's payload struct; the pointer is
    only valid until ManualDispatch_FreeLastCallback, so the pump copies
    the bytes out before freeing. (steam_api_internal.h:192)
    """

    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_hSteamUser", ctypes.c_int32),   # HSteamUser the callback is for
        ("m_iCallback", ctypes.c_int32),    # which callback this is (k_iCallback)
        ("m_pubParam", ctypes.POINTER(ctypes.c_uint8)),  # payload bytes
        ("m_cubParam", ctypes.c_int32),     # payload size in bytes
    ]


class SteamAPICallCompleted_t(ctypes.Structure):
    """Signals that an async call (a SteamAPICall_t handle) finished.

    The pump never hands this to user code: it reads the INNER
    m_iCallback (the result struct's id) and m_cubParam (the result
    size), fetches the result with ManualDispatch_GetAPICallResult, and
    delivers the decoded result instead. (isteamutils.h:264)
    """

    k_iCallback = 703  # k_iSteamUtilsCallbacks + 3
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_hAsyncCall", ctypes.c_uint64),  # SteamAPICall_t being completed
        ("m_iCallback", ctypes.c_int32),    # k_iCallback of the RESULT struct
        ("m_cubParam", ctypes.c_uint32),    # size of the result struct
    ]


# ---------------------------------------------------------------------------
# Matchmaking callbacks (isteammatchmaking.h) -- platform pack(4)/pack(8)
# ---------------------------------------------------------------------------

class LobbyInvite_t(ctypes.Structure):
    """Someone invited us to a lobby while we're in-game. (id 503)"""

    k_iCallback = 503
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_ulSteamIDUser", ctypes.c_uint64),   # who sent the invite
        ("m_ulSteamIDLobby", ctypes.c_uint64),  # the lobby we're invited to
        ("m_ulGameID", ctypes.c_uint64),        # CGameID of the lobby
    ]


class LobbyEnter_t(ctypes.Structure):
    """We entered a lobby -- or failed to. (id 504)

    Arrives BOTH as the call-result of JoinLobby and as a plain
    broadcast callback (including when entering our own new lobby).
    m_EChatRoomEnterResponse is an EChatRoomEnterResponse value;
    success == 1.
    """

    k_iCallback = 504
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_ulSteamIDLobby", ctypes.c_uint64),
        ("m_rgfChatPermissions", ctypes.c_uint32),  # unused by Valve, always 0
        ("m_bLocked", ctypes.c_bool),               # only invited users may join
        ("m_EChatRoomEnterResponse", ctypes.c_uint32),
    ]


class LobbyDataUpdate_t(ctypes.Structure):
    """Lobby or member metadata changed. (id 505)

    If m_ulSteamIDMember == m_ulSteamIDLobby the lobby's own data
    changed (read with GetLobbyData); otherwise that member's data
    changed (read with GetLobbyMemberData).
    """

    k_iCallback = 505
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_ulSteamIDLobby", ctypes.c_uint64),
        ("m_ulSteamIDMember", ctypes.c_uint64),
        ("m_bSuccess", ctypes.c_uint8),  # false only if the lobby no longer exists
    ]


class LobbyChatUpdate_t(ctypes.Structure):
    """A member joined, left, or was removed from a lobby. (id 506)

    m_rgfChatMemberStateChange is an EChatMemberStateChange bitfield.
    """

    k_iCallback = 506
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_ulSteamIDLobby", ctypes.c_uint64),
        ("m_ulSteamIDUserChanged", ctypes.c_uint64),   # whose state changed
        ("m_ulSteamIDMakingChange", ctypes.c_uint64),  # who caused it (kicks etc.)
        ("m_rgfChatMemberStateChange", ctypes.c_uint32),
    ]


class LobbyChatMsg_t(ctypes.Structure):
    """A lobby chat message arrived; fetch it with GetLobbyChatEntry. (id 507)"""

    k_iCallback = 507
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_ulSteamIDLobby", ctypes.c_uint64),
        ("m_ulSteamIDUser", ctypes.c_uint64),   # sender
        ("m_eChatEntryType", ctypes.c_uint8),   # EChatEntryType
        ("m_iChatID", ctypes.c_uint32),         # pass to GetLobbyChatEntry
    ]


class LobbyMatchList_t(ctypes.Structure):
    """RequestLobbyList finished; iterate GetLobbyByIndex 0..N-1. (id 510)

    Arrives as the call-result of RequestLobbyList.
    """

    k_iCallback = 510
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_nLobbiesMatching", ctypes.c_uint32),
    ]


class LobbyCreated_t(ctypes.Structure):
    """CreateLobby finished. (id 513)

    Arrives as the call-result of CreateLobby. On success
    (m_eResult == k_EResultOK == 1) the lobby exists, we are already in
    it, and a LobbyEnter_t broadcast follows.
    """

    k_iCallback = 513
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_eResult", ctypes.c_int32),          # EResult
        ("m_ulSteamIDLobby", ctypes.c_uint64),  # 0 on failure
    ]


# ---------------------------------------------------------------------------
# Friends callbacks (isteamfriends.h) -- platform pack(4)/pack(8)
# ---------------------------------------------------------------------------

class PersonaStateChange_t(ctypes.Structure):
    """A friend's name/status/avatar changed. (id 304)"""

    k_iCallback = 304
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_ulSteamID", ctypes.c_uint64),
        ("m_nChangeFlags", ctypes.c_int32),  # EPersonaChange bitfield
    ]


class GameLobbyJoinRequested_t(ctypes.Structure):
    """The user accepted a lobby invite or clicked 'Join Game'. (id 333)

    The standard response is SteamAPI_ISteamMatchmaking_JoinLobby on
    m_steamIDLobby.
    """

    k_iCallback = 333
    _pack_ = PACK_VALVE_CALLBACK
    _fields_ = [
        ("m_steamIDLobby", ctypes.c_uint64),
        ("m_steamIDFriend", ctypes.c_uint64),  # 0 if not via a specific friend
    ]


# ---------------------------------------------------------------------------
# SteamNetworking value types (steamnetworkingtypes.h) -- pack(1) / natural
# ---------------------------------------------------------------------------

class SteamNetworkingIPAddr(ctypes.Structure):
    """An IPv6 address+port (IPv4 appears as a mapped address). 18 bytes.

    Present because SteamNetworkingIdentity and SteamNetConnectionInfo_t
    embed it; this binding never constructs one directly.
    """

    _pack_ = 1
    _fields_ = [
        ("m_ipv6", ctypes.c_uint8 * 16),
        ("m_port", ctypes.c_uint16),  # host byte order
    ]


class _SteamNetworkingIdentityUnion(ctypes.Union):
    """The identity payload -- 128 bytes, interpreted per m_eType."""

    _pack_ = 1
    _fields_ = [
        ("m_steamID64", ctypes.c_uint64),       # when m_eType == SteamID (16)
        ("m_ip", SteamNetworkingIPAddr),        # when m_eType == IPAddress (1)
        ("m_szUnknownRawString", ctypes.c_char * 128),
        ("m_reserved", ctypes.c_uint32 * 32),   # the union's full 128-byte extent
    ]


class SteamNetworkingIdentity(ctypes.Structure):
    """Who a network peer is. 136 bytes, pack(1), same on every platform.

    For this binding's slice an identity is always a SteamID. Build one
    with Valve's own flat helper rather than poking fields:

        ident = pysteamnet.SteamNetworkingIdentity()
        pysteamnet.SteamAPI_SteamNetworkingIdentity_SetSteamID64(ident, steamid64)

    (That helper sets m_eType = 16, m_cbSize = 8, and writes the id into
    the union -- delegating the layout knowledge to Valve's code.)
    """

    _pack_ = 1
    _anonymous_ = ("_union",)
    _fields_ = [
        ("m_eType", ctypes.c_int32),   # ESteamNetworkingIdentityType
        ("m_cbSize", ctypes.c_int32),  # bytes of the union actually used
        ("_union", _SteamNetworkingIdentityUnion),
    ]


class SteamNetConnectionInfo_t(ctypes.Structure):
    """Describes a connection/session. 696 bytes on every platform.

    The header defines this under the platform pack(4)/pack(8) region
    (steamnetworkingtypes.h:673), but its layout is packing-independent
    (Valve padded it explicitly), so our pack(1) declaration is
    byte-identical and embeds cleanly in the pack(1) SessionFailed_t.

    Embedded in SteamNetworkingMessagesSessionFailed_t; the fields you
    will actually read there are m_identityRemote (who the session was
    with), m_eState, m_eEndReason, and m_szEndDebug.
    """

    _pack_ = 1
    _fields_ = [
        ("m_identityRemote", SteamNetworkingIdentity),
        ("m_nUserData", ctypes.c_int64),
        ("m_hListenSocket", ctypes.c_uint32),       # HSteamListenSocket
        ("m_addrRemote", SteamNetworkingIPAddr),
        ("m__pad1", ctypes.c_uint16),
        ("m_idPOPRemote", ctypes.c_uint32),          # SteamNetworkingPOPID
        ("m_idPOPRelay", ctypes.c_uint32),
        ("m_eState", ctypes.c_int32),                # ESteamNetworkingConnectionState
        ("m_eEndReason", ctypes.c_int32),
        ("m_szEndDebug", ctypes.c_char * 128),
        ("m_szConnectionDescription", ctypes.c_char * 128),
        ("m_nFlags", ctypes.c_int32),
        ("reserved", ctypes.c_uint32 * 63),
    ]


class SteamNetworkingMessage_t(ctypes.Structure):
    """A received message. Natural alignment (no pack pragma).

    User code never sees this struct: ReceiveMessagesOnChannel copies
    the payload to Python bytes and releases the message immediately
    (via SteamAPI_SteamNetworkingMessage_t_Release -- NEVER by calling
    the m_pfnRelease pointer from Python). The function-pointer fields
    appear as opaque c_void_p purely to keep the layout right.
    """

    _fields_ = [
        ("m_pData", ctypes.c_void_p),
        ("m_cbSize", ctypes.c_int32),
        ("m_conn", ctypes.c_uint32),          # HSteamNetConnection; unused here
        ("m_identityPeer", SteamNetworkingIdentity),
        ("m_nConnUserData", ctypes.c_int64),
        ("m_usecTimeReceived", ctypes.c_int64),
        ("m_nMessageNumber", ctypes.c_int64),
        ("m_pfnFreeData", ctypes.c_void_p),   # do not call from Python
        ("m_pfnRelease", ctypes.c_void_p),    # do not call from Python
        ("m_nChannel", ctypes.c_int32),
        ("m_nFlags", ctypes.c_int32),         # only the Reliable bit is valid on receive
        ("m_nUserData", ctypes.c_int64),
        ("m_idxLane", ctypes.c_uint16),
        ("_pad1__", ctypes.c_uint16),
    ]


# ---------------------------------------------------------------------------
# NetworkingMessages callbacks (isteamnetworkingmessages.h:133-163) -- pack(1)
# ---------------------------------------------------------------------------

class SteamNetworkingMessagesSessionRequest_t(ctypes.Structure):
    """A peer wants to message us and no session exists yet. (id 1251)

    Respond with AcceptSessionWithUser(m_identityRemote) to let their
    messages through (not needed if we message them first).
    """

    k_iCallback = 1251
    _pack_ = 1
    _fields_ = [
        ("m_identityRemote", SteamNetworkingIdentity),
    ]


class SteamNetworkingMessagesSessionFailed_t(ctypes.Structure):
    """A session could not be established, or broke unusually. (id 1252)

    m_info.m_identityRemote says who; m_info.m_eEndReason and
    m_info.m_szEndDebug say why. Note: a peer closing normally does NOT
    produce this -- UDP-style sessions have no "closed by peer" event.
    """

    k_iCallback = 1252
    _pack_ = 1
    _fields_ = [
        ("m_info", SteamNetConnectionInfo_t),
    ]


# ---------------------------------------------------------------------------
# The registry the dispatch pump routes by: callback id -> struct class.
# ---------------------------------------------------------------------------

CALLBACK_REGISTRY = {
    cls.k_iCallback: cls
    for cls in (
        LobbyInvite_t,
        LobbyEnter_t,
        LobbyDataUpdate_t,
        LobbyChatUpdate_t,
        LobbyChatMsg_t,
        LobbyMatchList_t,
        LobbyCreated_t,
        PersonaStateChange_t,
        GameLobbyJoinRequested_t,
        SteamNetworkingMessagesSessionRequest_t,
        SteamNetworkingMessagesSessionFailed_t,
    )
}

# A buffer type for SteamAPI_InitFlat's out-parameter (char[1024]).
# Usage: err = SteamErrMsg(); SteamAPI_InitFlat(err); err.value.decode()
SteamErrMsg = ctypes.c_char * 1024
