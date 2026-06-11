"""Valve's enums and constants, mirrored name-for-name and value-for-value.

Everything here is copied verbatim from the Steamworks SDK v1.64 headers
and steam_api.json -- these names and numbers are part of Valve's C API,
so mirroring them is fidelity, not invention. Each enum is a Python
IntEnum (or IntFlag for bitmasks): members compare equal to plain ints,
pass straight through ctypes, and print readably in logs.

Every member is ALSO re-exported as a module-level constant at the
bottom of this file, so Python code reads exactly like the C:

    pysteamnet.k_ELobbyTypePublic        # == ELobbyType.k_ELobbyTypePublic == 2

Sources: isteammatchmaking.h, isteamfriends.h, steamclientpublic.h,
steamnetworkingtypes.h, steam_api.h (SDK v1.64).
"""

import enum


class ESteamAPIInitResult(enum.IntEnum):
    """Result of SteamAPI_InitFlat (steam_api.h)."""

    k_ESteamAPIInitResult_OK = 0
    k_ESteamAPIInitResult_FailedGeneric = 1   # Some other failure -- check the SteamErrMsg text.
    k_ESteamAPIInitResult_NoSteamClient = 2   # Steam isn't running, or you're not logged in.
    k_ESteamAPIInitResult_VersionMismatch = 3  # The Steam client is older than this SDK.


class ELobbyType(enum.IntEnum):
    """Who can see and join a lobby (isteammatchmaking.h)."""

    k_ELobbyTypePrivate = 0        # Joinable only by invite.
    k_ELobbyTypeFriendsOnly = 1    # Visible to friends of members.
    k_ELobbyTypePublic = 2         # Returned by lobby searches.
    k_ELobbyTypeInvisible = 3      # Joinable by invite; never listed.
    k_ELobbyTypePrivateUnique = 4  # Private, persistent, one per keypair.


class ELobbyComparison(enum.IntEnum):
    """Comparison operator for lobby search filters (isteammatchmaking.h)."""

    k_ELobbyComparisonEqualToOrLessThan = -2
    k_ELobbyComparisonLessThan = -1
    k_ELobbyComparisonEqual = 0
    k_ELobbyComparisonGreaterThan = 1
    k_ELobbyComparisonEqualToOrGreaterThan = 2
    k_ELobbyComparisonNotEqual = 3


class EChatMemberStateChange(enum.IntFlag):
    """Bitfield in LobbyChatUpdate_t -- why a member's state changed."""

    k_EChatMemberStateChangeEntered = 0x0001
    k_EChatMemberStateChangeLeft = 0x0002
    k_EChatMemberStateChangeDisconnected = 0x0004
    k_EChatMemberStateChangeKicked = 0x0008
    k_EChatMemberStateChangeBanned = 0x0010


class EChatEntryType(enum.IntEnum):
    """Type of a lobby chat entry (steamclientpublic.h)."""

    k_EChatEntryTypeInvalid = 0
    k_EChatEntryTypeChatMsg = 1
    k_EChatEntryTypeTyping = 2
    k_EChatEntryTypeInviteGame = 3
    k_EChatEntryTypeEmote = 4
    k_EChatEntryTypeLeftConversation = 6
    k_EChatEntryTypeEntered = 7
    k_EChatEntryTypeWasKicked = 8
    k_EChatEntryTypeWasBanned = 9
    k_EChatEntryTypeDisconnected = 10
    k_EChatEntryTypeHistoricalChat = 11
    k_EChatEntryTypeLinkBlocked = 14


class EChatRoomEnterResponse(enum.IntEnum):
    """LobbyEnter_t.m_EChatRoomEnterResponse values (steamclientpublic.h)."""

    k_EChatRoomEnterResponseSuccess = 1
    k_EChatRoomEnterResponseDoesntExist = 2
    k_EChatRoomEnterResponseNotAllowed = 3
    k_EChatRoomEnterResponseFull = 4
    k_EChatRoomEnterResponseError = 5
    k_EChatRoomEnterResponseBanned = 6
    k_EChatRoomEnterResponseLimited = 7
    k_EChatRoomEnterResponseClanDisabled = 8
    k_EChatRoomEnterResponseCommunityBan = 9
    k_EChatRoomEnterResponseMemberBlockedYou = 10
    k_EChatRoomEnterResponseYouBlockedMember = 11
    k_EChatRoomEnterResponseRatelimitExceeded = 15


class EPersonaState(enum.IntEnum):
    """A friend's online status (isteamfriends.h)."""

    k_EPersonaStateOffline = 0
    k_EPersonaStateOnline = 1
    k_EPersonaStateBusy = 2
    k_EPersonaStateAway = 3
    k_EPersonaStateSnooze = 4
    k_EPersonaStateLookingToTrade = 5
    k_EPersonaStateLookingToPlay = 6
    k_EPersonaStateInvisible = 7
    k_EPersonaStateMax = 8


class ESteamNetworkingIdentityType(enum.IntEnum):
    """What kind of host a SteamNetworkingIdentity names (steamnetworkingtypes.h).

    For this binding's slice the only type that matters is SteamID (16);
    the rest are mirrored so the enum is complete.
    """

    k_ESteamNetworkingIdentityType_Invalid = 0
    k_ESteamNetworkingIdentityType_IPAddress = 1
    k_ESteamNetworkingIdentityType_GenericString = 2
    k_ESteamNetworkingIdentityType_GenericBytes = 3
    k_ESteamNetworkingIdentityType_UnknownType = 4
    k_ESteamNetworkingIdentityType_SteamID = 16
    k_ESteamNetworkingIdentityType_XboxPairwiseID = 17
    k_ESteamNetworkingIdentityType_SonyPSN = 18


class ESteamNetworkingConnectionState(enum.IntEnum):
    """High-level session/connection state (steamnetworkingtypes.h)."""

    k_ESteamNetworkingConnectionState_Dead = -3
    k_ESteamNetworkingConnectionState_Linger = -2
    k_ESteamNetworkingConnectionState_FinWait = -1
    k_ESteamNetworkingConnectionState_None = 0
    k_ESteamNetworkingConnectionState_Connecting = 1
    k_ESteamNetworkingConnectionState_FindingRoute = 2
    k_ESteamNetworkingConnectionState_Connected = 3
    k_ESteamNetworkingConnectionState_ClosedByPeer = 4
    k_ESteamNetworkingConnectionState_ProblemDetectedLocally = 5


class EResult(enum.IntEnum):
    """Valve's universal result code (steamclientpublic.h) -- mirrored in
    full because it is the return value of SendMessageToUser and the
    m_eResult of many callbacks: exactly the thing you are staring at
    while debugging a failure. Note k_EResultOK is 1, not 0, and the
    capital-K typo in K_EResultPhoneNumberIsVOIP is Valve's own.
    """

    k_EResultNone = 0
    k_EResultOK = 1
    k_EResultFail = 2
    k_EResultNoConnection = 3
    k_EResultInvalidPassword = 5
    k_EResultLoggedInElsewhere = 6
    k_EResultInvalidProtocolVer = 7
    k_EResultInvalidParam = 8
    k_EResultFileNotFound = 9
    k_EResultBusy = 10
    k_EResultInvalidState = 11
    k_EResultInvalidName = 12
    k_EResultInvalidEmail = 13
    k_EResultDuplicateName = 14
    k_EResultAccessDenied = 15
    k_EResultTimeout = 16
    k_EResultBanned = 17
    k_EResultAccountNotFound = 18
    k_EResultInvalidSteamID = 19
    k_EResultServiceUnavailable = 20
    k_EResultNotLoggedOn = 21
    k_EResultPending = 22
    k_EResultEncryptionFailure = 23
    k_EResultInsufficientPrivilege = 24
    k_EResultLimitExceeded = 25
    k_EResultRevoked = 26
    k_EResultExpired = 27
    k_EResultAlreadyRedeemed = 28
    k_EResultDuplicateRequest = 29
    k_EResultAlreadyOwned = 30
    k_EResultIPNotFound = 31
    k_EResultPersistFailed = 32
    k_EResultLockingFailed = 33
    k_EResultLogonSessionReplaced = 34
    k_EResultConnectFailed = 35
    k_EResultHandshakeFailed = 36
    k_EResultIOFailure = 37
    k_EResultRemoteDisconnect = 38
    k_EResultShoppingCartNotFound = 39
    k_EResultBlocked = 40
    k_EResultIgnored = 41
    k_EResultNoMatch = 42
    k_EResultAccountDisabled = 43
    k_EResultServiceReadOnly = 44
    k_EResultAccountNotFeatured = 45
    k_EResultAdministratorOK = 46
    k_EResultContentVersion = 47
    k_EResultTryAnotherCM = 48
    k_EResultPasswordRequiredToKickSession = 49
    k_EResultAlreadyLoggedInElsewhere = 50
    k_EResultSuspended = 51
    k_EResultCancelled = 52
    k_EResultDataCorruption = 53
    k_EResultDiskFull = 54
    k_EResultRemoteCallFailed = 55
    k_EResultPasswordUnset = 56
    k_EResultExternalAccountUnlinked = 57
    k_EResultPSNTicketInvalid = 58
    k_EResultExternalAccountAlreadyLinked = 59
    k_EResultRemoteFileConflict = 60
    k_EResultIllegalPassword = 61
    k_EResultSameAsPreviousValue = 62
    k_EResultAccountLogonDenied = 63
    k_EResultCannotUseOldPassword = 64
    k_EResultInvalidLoginAuthCode = 65
    k_EResultAccountLogonDeniedNoMail = 66
    k_EResultHardwareNotCapableOfIPT = 67
    k_EResultIPTInitError = 68
    k_EResultParentalControlRestricted = 69
    k_EResultFacebookQueryError = 70
    k_EResultExpiredLoginAuthCode = 71
    k_EResultIPLoginRestrictionFailed = 72
    k_EResultAccountLockedDown = 73
    k_EResultAccountLogonDeniedVerifiedEmailRequired = 74
    k_EResultNoMatchingURL = 75
    k_EResultBadResponse = 76
    k_EResultRequirePasswordReEntry = 77
    k_EResultValueOutOfRange = 78
    k_EResultUnexpectedError = 79
    k_EResultDisabled = 80
    k_EResultInvalidCEGSubmission = 81
    k_EResultRestrictedDevice = 82
    k_EResultRegionLocked = 83
    k_EResultRateLimitExceeded = 84
    k_EResultAccountLoginDeniedNeedTwoFactor = 85
    k_EResultItemDeleted = 86
    k_EResultAccountLoginDeniedThrottle = 87
    k_EResultTwoFactorCodeMismatch = 88
    k_EResultTwoFactorActivationCodeMismatch = 89
    k_EResultAccountAssociatedToMultiplePartners = 90
    k_EResultNotModified = 91
    k_EResultNoMobileDevice = 92
    k_EResultTimeNotSynced = 93
    k_EResultSmsCodeFailed = 94
    k_EResultAccountLimitExceeded = 95
    k_EResultAccountActivityLimitExceeded = 96
    k_EResultPhoneActivityLimitExceeded = 97
    k_EResultRefundToWallet = 98
    k_EResultEmailSendFailure = 99
    k_EResultNotSettled = 100
    k_EResultNeedCaptcha = 101
    k_EResultGSLTDenied = 102
    k_EResultGSOwnerDenied = 103
    k_EResultInvalidItemType = 104
    k_EResultIPBanned = 105
    k_EResultGSLTExpired = 106
    k_EResultInsufficientFunds = 107
    k_EResultTooManyPending = 108
    k_EResultNoSiteLicensesFound = 109
    k_EResultWGNetworkSendExceeded = 110
    k_EResultAccountNotFriends = 111
    k_EResultLimitedUserAccount = 112
    k_EResultCantRemoveItem = 113
    k_EResultAccountDeleted = 114
    k_EResultExistingUserCancelledLicense = 115
    k_EResultCommunityCooldown = 116
    k_EResultNoLauncherSpecified = 117
    k_EResultMustAgreeToSSA = 118
    k_EResultLauncherMigrated = 119
    k_EResultSteamRealmMismatch = 120
    k_EResultInvalidSignature = 121
    k_EResultParseFailure = 122
    k_EResultNoVerifiedPhone = 123
    k_EResultInsufficientBattery = 124
    k_EResultChargerRequired = 125
    k_EResultCachedCredentialInvalid = 126
    K_EResultPhoneNumberIsVOIP = 127
    k_EResultNotSupported = 128
    k_EResultFamilySizeLimitExceeded = 129
    k_EResultOfflineAppCacheInvalid = 130
    k_EResultTryLater = 131


# ---------------------------------------------------------------------------
# Plain int constants (these are `const int` in the headers, not enums).
# ---------------------------------------------------------------------------

# Send flags for SteamAPI_ISteamNetworkingMessages_SendMessageToUser.
# Combinable bitmask -- steamnetworkingtypes.h:963-1057. The two you will
# actually use: Reliable (ordered, retransmitted, like TCP) and
# UnreliableNoNagle (fire-and-forget, minimal latency, like raw UDP).
k_nSteamNetworkingSend_Unreliable = 0
k_nSteamNetworkingSend_NoNagle = 1
k_nSteamNetworkingSend_UnreliableNoNagle = 1      # Unreliable | NoNagle
k_nSteamNetworkingSend_NoDelay = 4
k_nSteamNetworkingSend_UnreliableNoDelay = 5      # Unreliable | NoDelay | NoNagle
k_nSteamNetworkingSend_Reliable = 8
k_nSteamNetworkingSend_ReliableNoNagle = 9        # Reliable | NoNagle
k_nSteamNetworkingSend_AutoRestartBrokenSession = 32

# Every known send-flag bit, for validation.
_ALL_SEND_FLAG_BITS = (
    k_nSteamNetworkingSend_NoNagle
    | k_nSteamNetworkingSend_NoDelay
    | k_nSteamNetworkingSend_Reliable
    | k_nSteamNetworkingSend_AutoRestartBrokenSession
)

# An async call handle that means "the call failed immediately"
# (steam_api_common.h). Compare SteamAPICall_t returns against this.
k_uAPICallInvalid = 0

# SteamAPI_InitFlat's error-message buffer length (steam_api_common.h).
k_cchMaxSteamErrMsg = 1024

# Largest payload SendMessageToUser accepts (steamnetworkingtypes.h:841).
k_cbMaxSteamNetworkingSocketsMessageSizeSend = 512 * 1024

# Longest lobby-data key, in bytes (isteammatchmaking.h:51).
k_nMaxLobbyKeyLength = 255

# Callback-ID bases (steam_api_internal.h) -- each interface's callbacks
# number upward from its base. The resolved per-struct IDs live on the
# struct classes in _structs.py as k_iCallback, exactly as in C++.
k_iSteamUserCallbacks = 100
k_iSteamFriendsCallbacks = 300
k_iSteamMatchmakingCallbacks = 500
k_iSteamUtilsCallbacks = 700
k_iSteamNetworkingMessagesCallbacks = 1250


# ---------------------------------------------------------------------------
# Re-export every enum member as a module-level constant, so call sites
# read exactly like the C they mirror (pysteamnet.k_ELobbyTypePublic).
# ---------------------------------------------------------------------------
def _export_members(*enum_classes):
    for cls in enum_classes:
        for name, member in cls.__members__.items():
            globals()[name] = member


_export_members(
    ESteamAPIInitResult, ELobbyType, ELobbyComparison, EChatMemberStateChange,
    EChatEntryType, EChatRoomEnterResponse, EPersonaState,
    ESteamNetworkingIdentityType, ESteamNetworkingConnectionState, EResult,
)
del _export_members

# Everything public in this module belongs in the package namespace
# (the enums, the k_* member aliases, and the plain int constants) --
# but not our own import of the stdlib enum module.
__all__ = [name for name in globals() if not name.startswith("_") and name != "enum"]
