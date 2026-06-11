"""Friendly argument checks that run before any call crosses into C.

Two validation layers protect every bound function:

  1. ctypes ``argtypes``/``restype`` declarations (stamped by
     _bindings.bind_signatures) -- the runtime equivalent of C's
     compile-time type checking. Wrong types raise at call time.
  2. The helpers in this module -- they catch values that are
     type-correct but semantically wrong (a zero SteamID, a str where
     the wire wants bytes, an out-of-range enum) and raise a clear
     TypeError/ValueError BEFORE the foreign call, with a message that
     says how to fix it.

These guards add no behavior and no opinions; they only convert what
would be a cryptic ctypes error (or a silent wrong answer inside Steam)
into a plain sentence.
"""


def check_bytes(name, value, max_len=None):
    """Require a bytes-like payload; reject str with the fix included."""
    if isinstance(value, str):
        raise TypeError(
            f"{name} must be bytes, got str. Encode it first, e.g. "
            f"{name}.encode('utf-8') -- Steam transports raw bytes, not text."
        )
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes, got {type(value).__name__}.")
    if max_len is not None and len(value) > max_len:
        raise ValueError(
            f"{name} is {len(value)} bytes, but Steam's maximum here is "
            f"{max_len} bytes. Split the payload into smaller messages."
        )


def check_steamid(name, value):
    """Require a plausible 64-bit SteamID (a non-zero unsigned int).

    A zero SteamID is always a bug -- usually an async result (like
    LobbyCreated_t) that has not arrived yet.
    """
    check_uint(name, value, bits=64)
    if value == 0:
        raise ValueError(
            f"{name} is 0, which is never a valid SteamID. If this came "
            f"from CreateLobby/JoinLobby, the async result may not have "
            f"arrived yet -- pump run_frame() and wait for the callback."
        )


def check_uint(name, value, bits):
    """Require an int in [0, 2**bits) -- what the C unsigned type holds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if not 0 <= value < (1 << bits):
        raise ValueError(
            f"{name} must fit an unsigned {bits}-bit integer "
            f"(0 <= value < 2**{bits}), got {value}."
        )


def check_int_range(name, value, low, high):
    """Require an int in the inclusive range [low, high]."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}.")


def check_enum(name, value, enum_cls):
    """Require a valid member (or member value) of one of Valve's enums."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be an int or {enum_cls.__name__} member, "
            f"got {type(value).__name__}."
        )
    try:
        enum_cls(value)
    except ValueError:
        valid = ", ".join(f"{m.name}={m.value}" for m in enum_cls)
        raise ValueError(
            f"{name}={value} is not a valid {enum_cls.__name__}. "
            f"Valid values: {valid}."
        ) from None


def check_flags(name, value, valid_bits):
    """Require an int whose set bits are all within ``valid_bits``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if value < 0 or (value & ~valid_bits):
        raise ValueError(
            f"{name}={value} contains bits outside the known flag set "
            f"0x{valid_bits:x}. Combine only the documented k_n* constants."
        )


def check_str(name, value, max_len=None):
    """Require a str for textual C parameters (we encode UTF-8 at the edge)."""
    if isinstance(value, (bytes, bytearray)):
        raise TypeError(
            f"{name} must be str, got bytes. This parameter is text "
            f"(C const char*); pysteamnet encodes it as UTF-8 for you."
        )
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str, got {type(value).__name__}.")
    if max_len is not None and len(value.encode("utf-8")) > max_len:
        raise ValueError(
            f"{name} is longer than Steam's limit of {max_len} bytes "
            f"(UTF-8 encoded)."
        )


def check_self_ptr(name, value):
    """Require a non-NULL interface pointer from a versioned accessor.

    Accessors return NULL until SteamAPI_InitFlat has succeeded, so a
    None here almost always means init was skipped or failed.
    """
    if value is None or value == 0:
        raise ValueError(
            f"{name} is NULL. Interface accessors (e.g. "
            f"SteamAPI_SteamMatchmaking_v009()) return NULL until "
            f"SteamAPI_InitFlat succeeds -- is the Steam client running "
            f"and did you check the init result?"
        )
