"""Cross-check our hand-written declarations against Valve's steam_api.json.

Marked ``sdk``: needs the unpacked Steamworks SDK on disk, pointed at by
the ``PYSTEAMNET_SDK`` environment variable (the repo's pinned SDK is
v1.64). Skips cleanly when that env var is unset or the JSON is missing,
so the pure tier stays runnable without the SDK.

``steam_api.json`` ships in ``public/steam/`` as a machine-readable
description of the flat API, intended for binding generators. We don't
generate from it -- we hand-declare and then verify against it here, so a
typo in FLAT_SIGNATURES (wrong arg count, wrong scalar width, a dropped
``callresult``) fails a test instead of silently corrupting a call.

Three groups:
  a. the five pinned interface accessors exist in the JSON,
  b. every ISteam* method in FLAT_SIGNATURES matches the JSON's
     parameter count / types / return type (and the three async lobby
     calls carry the right ``callresult`` struct),
  c. every callback struct in CALLBACK_REGISTRY matches the JSON's
     callback_id and field names/order.
"""

import ctypes
import json
import os

import pytest

import pysteamnet
from pysteamnet import _structs as st

pytestmark = pytest.mark.sdk


# ---------------------------------------------------------------------------
# Load the SDK JSON once for the whole module, or skip the whole file.
# ---------------------------------------------------------------------------

def _load_sdk_json():
    sdk_root = os.environ.get("PYSTEAMNET_SDK")
    if not sdk_root:
        pytest.skip("PYSTEAMNET_SDK not set; skipping SDK JSON cross-check.")
    path = os.path.join(
        os.path.expanduser(sdk_root), "public", "steam", "steam_api.json"
    )
    if not os.path.isfile(path):
        pytest.skip(f"steam_api.json not found at {path}; skipping cross-check.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def sdk_json():
    return _load_sdk_json()


@pytest.fixture(scope="module")
def flat_methods(sdk_json):
    """methodname_flat -> method dict, across every interface."""
    out = {}
    for iface in sdk_json["interfaces"]:
        for method in iface.get("methods", []):
            out[method["methodname_flat"]] = method
    return out


@pytest.fixture(scope="module")
def accessor_names(sdk_json):
    """The set of every interface accessor name_flat in the JSON.

    Each accessor is a dict like {"kind", "name", "name_flat"}; we collect
    the flat names, which are what FLAT_SIGNATURES pins (e.g.
    "SteamAPI_SteamUser_v023").
    """
    names = set()
    for iface in sdk_json["interfaces"]:
        for accessor in iface.get("accessors", []):
            names.add(accessor["name_flat"])
    return names


@pytest.fixture(scope="module")
def callback_by_struct(sdk_json):
    """struct name -> callback_struct dict."""
    return {cb["struct"]: cb for cb in sdk_json["callback_structs"]}


# ---------------------------------------------------------------------------
# The C-type -> ctypes resolver.
#
# The JSON describes parameter types as C type strings. To compare them to
# our ctypes declarations we resolve each to a ctypes type (or a small set
# of acceptable ctypes types), applying:
#   * one typedef hop from the JSON "typedefs" list
#     (e.g. SteamAPICall_t -> "unsigned long long"),
#   * a hand map of C scalar strings -> ctypes,
#   * enums (named in the JSON enum list) -> c_int,
#   * any "* "/"&" type -> a pointer (POINTER(struct) or c_void_p both ok).
# ---------------------------------------------------------------------------

#: C scalar type string -> the ctypes type we expect to see for it.
_SCALAR_MAP = {
    "int": ctypes.c_int,
    "unsigned int": ctypes.c_uint32,
    "unsigned long long": ctypes.c_uint64,
    "long long": ctypes.c_int64,
    "unsigned char": ctypes.c_uint8,
    "signed char": ctypes.c_int8,
    "short": ctypes.c_int16,
    "unsigned short": ctypes.c_uint16,
    "bool": ctypes.c_bool,
    "float": ctypes.c_float,
    "double": ctypes.c_double,
    "void": None,
    "const char *": ctypes.c_char_p,
    "char *": ctypes.c_char_p,
    "void *": ctypes.c_void_p,
    "const void *": ctypes.c_void_p,
}

#: Some flat scalar typedefs we accept as their own width directly, so we
#: don't depend on a particular spelling surviving a typedef hop.
_DIRECT_TYPEDEF_CTYPE = {
    "uint32": ctypes.c_uint32,
    "int32": ctypes.c_int32,
    "uint64": ctypes.c_uint64,
    "int64": ctypes.c_int64,
    "uint16": ctypes.c_uint16,
    "int16": ctypes.c_int16,
    "uint8": ctypes.c_uint8,
    "int8": ctypes.c_int8,
    "uint64_steamid": ctypes.c_uint64,
    "uint64_gameid": ctypes.c_uint64,
    # The C++ class names CSteamID/CGameID appear bare as RETURN types in
    # the JSON (params get a paramtype_flat of uint64_steamid instead). The
    # flat C API collapses both to a 64-bit value, which is how we declare
    # them -- so accept c_uint64 for the bare class names too.
    "CSteamID": ctypes.c_uint64,
    "CGameID": ctypes.c_uint64,
}

#: The struct types the flat API hands us pointers/references to, by name.
_STRUCT_BY_NAME = {
    "SteamNetworkingIdentity": st.SteamNetworkingIdentity,
    "SteamNetConnectionInfo_t": st.SteamNetConnectionInfo_t,
    "SteamNetworkingMessage_t": st.SteamNetworkingMessage_t,
}


def _build_typedef_resolver(sdk_json):
    """typedef name -> its underlying C type string (one hop)."""
    return {t["typedef"]: t["type"] for t in sdk_json["typedefs"]}


def _enum_names(sdk_json):
    return {e["enumname"] for e in sdk_json["enums"]}


def _is_pointerish(ctype):
    """True if a ctypes type is some kind of pointer (POINTER, c_void_p, c_char_p)."""
    if ctype in (ctypes.c_void_p, ctypes.c_char_p):
        return True
    # POINTER(...) types and function pointers are ctypes._Pointer / CFUNCTYPE;
    # the robust check is "has a _type_ and is a pointer class".
    try:
        return issubclass(ctype, ctypes._Pointer)
    except TypeError:
        return False


def resolve_param_type(type_str, typedefs, enum_names):
    """Return a list of ctypes types acceptable for a JSON C type string.

    A list, because for pointer-ish types we accept either the precise
    POINTER(struct) or a plain c_void_p -- both are honest ctypes mappings
    of a C pointer, and the binding legitimately uses each in places.
    """
    type_str = type_str.strip()

    # Pointer or reference: "Foo *", "const Foo &", "Foo **", etc.
    # ctypes erases the layers, so any pointer arg is accepted as either a
    # typed POINTER or an opaque c_void_p.
    if type_str.endswith("*") or type_str.endswith("&"):
        acceptable = [ctypes.c_void_p]
        # char* maps to c_char_p, the idiomatic string pointer.
        base = type_str.rstrip("*&").strip()
        if base in ("const char", "char"):
            acceptable.append(ctypes.c_char_p)
        # If it names a struct we know, POINTER(that struct) is also fine,
        # at any pointer depth (single or double pointer).
        for name, cls in _STRUCT_BY_NAME.items():
            if name in base:
                acceptable.append(ctypes.POINTER(cls))
                acceptable.append(ctypes.POINTER(ctypes.POINTER(cls)))
        return acceptable

    # Whole-string scalar (covers "const char *" etc. that we map directly).
    if type_str in _SCALAR_MAP:
        return [_SCALAR_MAP[type_str]]

    # Flat scalar typedef we accept by width directly.
    if type_str in _DIRECT_TYPEDEF_CTYPE:
        return [_DIRECT_TYPEDEF_CTYPE[type_str]]

    # Enum -> c_int (the JSON enum list is the authority on what's an enum).
    if type_str in enum_names:
        return [ctypes.c_int]

    # One typedef hop, then re-resolve the underlying C type.
    if type_str in typedefs:
        underlying = typedefs[type_str]
        if underlying != type_str:  # guard against a self-referential typedef
            return resolve_param_type(underlying, typedefs, enum_names)

    # Unknown -- return empty; the caller turns that into a clear failure.
    return []


def _ctype_compatible(declared, acceptable):
    """Is our declared ctypes arg compatible with any resolved option?

    Exact match first. Then the deliberate looseness: a c_int declaration
    is compatible with c_int32 (same width, same thing) and vice versa,
    and any two pointer-ish ctypes are mutually acceptable (C erases the
    pointee for call purposes).
    """
    if not acceptable:
        return False
    if declared in acceptable:
        return True

    # c_int / c_int32 are the same machine type; treat as interchangeable.
    int_aliases = {ctypes.c_int, ctypes.c_int32}
    if declared in int_aliases and any(a in int_aliases for a in acceptable):
        return True
    uint_aliases = {ctypes.c_uint, ctypes.c_uint32}
    if declared in uint_aliases and any(a in uint_aliases for a in acceptable):
        return True

    # Pointer looseness: our c_void_p is acceptable wherever C wants a
    # pointer, and our typed POINTER is acceptable wherever we'd also allow
    # c_void_p (the resolver always offers c_void_p for pointer args).
    if _is_pointerish(declared) and any(_is_pointerish(a) for a in acceptable):
        return True

    return False


# ---------------------------------------------------------------------------
# Group (a): the five pinned interface accessors exist.
# ---------------------------------------------------------------------------

PINNED_ACCESSORS = [
    "SteamAPI_SteamUser_v023",
    "SteamAPI_SteamFriends_v018",
    "SteamAPI_SteamUtils_v010",
    "SteamAPI_SteamMatchmaking_v009",
    "SteamAPI_SteamNetworkingMessages_SteamAPI_v002",
]


@pytest.mark.parametrize("accessor", PINNED_ACCESSORS)
def test_pinned_accessor_present_in_sdk(accessor, accessor_names):
    """Each version-pinned accessor name still exists in this SDK's JSON.

    If one of these ever disappears it means the SDK bumped that
    interface's version and our _vNNN pin is stale -- a real break.
    """
    assert accessor in accessor_names, (
        f"{accessor} is not an accessor in steam_api.json -- the pinned "
        f"interface version may have changed in this SDK."
    )


# ---------------------------------------------------------------------------
# Group (b): flat method signatures match the JSON.
# ---------------------------------------------------------------------------

_OUR_ISTEAM_METHODS = sorted(
    n for n in pysteamnet.FLAT_SIGNATURES if n.startswith("SteamAPI_ISteam")
)


@pytest.mark.parametrize("name", _OUR_ISTEAM_METHODS)
def test_method_argcount_matches_json(name, flat_methods):
    """len(our argtypes) == 1 (self pointer) + len(JSON params).

    Note we assert this for ALL of our ISteam* methods including the two
    "managed" wrappers (ReceiveMessagesOnChannel, GetLobbyChatEntry): the
    Python-facing signatures hide out-params, but FLAT_SIGNATURES declares
    the FULL C argtypes, so no method is exempt here.
    """
    method = flat_methods.get(name)
    assert method is not None, f"{name} not found in steam_api.json interfaces."

    argtypes, _restype = pysteamnet.FLAT_SIGNATURES[name]
    expected = 1 + len(method["params"])  # +1 for the leading self pointer
    assert len(argtypes) == expected, (
        f"{name}: declared {len(argtypes)} argtypes but JSON has "
        f"{len(method['params'])} params (+1 self = {expected})."
    )


@pytest.mark.parametrize("name", _OUR_ISTEAM_METHODS)
def test_method_argtypes_match_json(name, flat_methods, sdk_json):
    """Each declared argtype is compatible with the resolved JSON param type.

    The leading self pointer must be a pointer; each remaining argtype must
    resolve-compatibly against the corresponding JSON parameter (using its
    flat type when the JSON gives one, e.g. uint64_steamid for CSteamID).
    """
    method = flat_methods[name]
    typedefs = _build_typedef_resolver(sdk_json)
    enums = _enum_names(sdk_json)

    argtypes, _restype = pysteamnet.FLAT_SIGNATURES[name]

    # arg 0 is the ISteam* self pointer; we always declare c_void_p.
    assert _is_pointerish(argtypes[0]), (
        f"{name}: first argtype should be a pointer (the self handle), "
        f"got {argtypes[0]}."
    )

    for i, param in enumerate(method["params"]):
        declared = argtypes[i + 1]
        # Prefer the flat type string when the JSON provides one.
        type_str = param.get("paramtype_flat", param["paramtype"])
        acceptable = resolve_param_type(type_str, typedefs, enums)
        assert acceptable, (
            f"{name} param {param['paramname']!r}: could not resolve JSON "
            f"type {type_str!r} to a ctypes type -- update the resolver map."
        )
        assert _ctype_compatible(declared, acceptable), (
            f"{name} param {param['paramname']!r}: declared {declared} is "
            f"not compatible with JSON type {type_str!r} "
            f"(resolved to {acceptable})."
        )


@pytest.mark.parametrize("name", _OUR_ISTEAM_METHODS)
def test_method_restype_matches_json(name, flat_methods, sdk_json):
    """Our restype is compatible with the JSON returntype.

    Enums return as C int, so a c_int restype against an enum returntype is
    a match. void <-> None. Pointers (const char * -> c_char_p) line up.
    """
    method = flat_methods[name]
    typedefs = _build_typedef_resolver(sdk_json)
    enums = _enum_names(sdk_json)

    _argtypes, restype = pysteamnet.FLAT_SIGNATURES[name]
    returntype = method["returntype"].strip()

    if returntype == "void":
        assert restype is None, f"{name}: JSON returns void but restype is {restype}."
        return

    acceptable = resolve_param_type(returntype, typedefs, enums)
    assert acceptable, (
        f"{name}: could not resolve JSON returntype {returntype!r}."
    )
    assert _ctype_compatible(restype, acceptable), (
        f"{name}: restype {restype} not compatible with JSON returntype "
        f"{returntype!r} (resolved to {acceptable})."
    )


def test_lobby_calls_carry_expected_callresult(flat_methods):
    """The three async lobby calls declare the right call-result struct.

    CreateLobby -> LobbyCreated_t, JoinLobby -> LobbyEnter_t,
    RequestLobbyList -> LobbyMatchList_t. This is the contract our
    take_call_result() decoder relies on: the call's handle resolves to
    that struct's k_iCallback.
    """
    expected = {
        "SteamAPI_ISteamMatchmaking_CreateLobby": "LobbyCreated_t",
        "SteamAPI_ISteamMatchmaking_JoinLobby": "LobbyEnter_t",
        "SteamAPI_ISteamMatchmaking_RequestLobbyList": "LobbyMatchList_t",
    }
    for flat_name, callresult in expected.items():
        method = flat_methods.get(flat_name)
        assert method is not None, f"{flat_name} missing from JSON."
        assert method.get("callresult") == callresult, (
            f"{flat_name}: JSON callresult is {method.get('callresult')!r}, "
            f"expected {callresult!r}."
        )


# ---------------------------------------------------------------------------
# Group (c): callback structs match the JSON.
# ---------------------------------------------------------------------------

#: Coarse map from a JSON callback fieldtype string to the ctypes type(s)
#: we'll accept for the matching field. Deliberately loose: Valve declares
#: SteamIDs variously as uint64 / CSteamID, and "bool" fields show up as a
#: uint8 byte in some of our structs and as c_bool in others -- both are a
#: single byte and are honest.
def _acceptable_field_ctypes(fieldtype):
    fieldtype = fieldtype.strip()
    table = {
        "uint64": {ctypes.c_uint64},
        "CSteamID": {ctypes.c_uint64},
        "uint64_steamid": {ctypes.c_uint64},
        "CGameID": {ctypes.c_uint64},
        "uint64_gameid": {ctypes.c_uint64},
        "uint32": {ctypes.c_uint32},
        "int32": {ctypes.c_int32, ctypes.c_int},
        "uint8": {ctypes.c_uint8, ctypes.c_bool},
        "bool": {ctypes.c_bool, ctypes.c_uint8},
        "int": {ctypes.c_int32, ctypes.c_int},
        "EResult": {ctypes.c_int32, ctypes.c_int},
        "SteamNetworkingIdentity": {st.SteamNetworkingIdentity},
        "SteamNetConnectionInfo_t": {st.SteamNetConnectionInfo_t},
    }
    return table.get(fieldtype)


@pytest.mark.parametrize(
    "callback_id",
    sorted(pysteamnet.CALLBACK_REGISTRY),
    ids=lambda cid: pysteamnet.CALLBACK_REGISTRY[cid].__name__,
)
def test_callback_struct_matches_json(callback_id, callback_by_struct):
    """For each registered callback: id, field names/order, field types.

    The JSON is the authority on the callback's id, on its field names and
    their order, and (coarsely) on each field's type. A reordered or
    renamed field here would silently misread every callback of that kind.
    """
    cls = pysteamnet.CALLBACK_REGISTRY[callback_id]
    json_cb = callback_by_struct.get(cls.__name__)
    assert json_cb is not None, (
        f"{cls.__name__} not found in steam_api.json callback_structs."
    )

    # 1) callback_id matches our k_iCallback (and the registry key).
    assert json_cb["callback_id"] == cls.k_iCallback == callback_id, (
        f"{cls.__name__}: JSON callback_id={json_cb['callback_id']}, "
        f"our k_iCallback={cls.k_iCallback}, registry key={callback_id}."
    )

    # 2) field names match the JSON, in order.
    our_field_names = [name for name, _ctype in cls._fields_]
    json_field_names = [f["fieldname"] for f in json_cb["fields"]]
    assert our_field_names == json_field_names, (
        f"{cls.__name__}: field names/order differ.\n"
        f"  ours: {our_field_names}\n  json: {json_field_names}"
    )

    # 3) each field's ctype is in the coarse acceptable set for its JSON type.
    our_field_types = dict(cls._fields_)
    for field in json_cb["fields"]:
        fname = field["fieldname"]
        fjson_type = field["fieldtype"]
        declared = our_field_types[fname]
        acceptable = _acceptable_field_ctypes(fjson_type)
        assert acceptable is not None, (
            f"{cls.__name__}.{fname}: JSON fieldtype {fjson_type!r} not in "
            f"the coarse field-type map -- extend it."
        )
        assert declared in acceptable, (
            f"{cls.__name__}.{fname}: declared {declared} not compatible "
            f"with JSON fieldtype {fjson_type!r} (accepts {acceptable})."
        )
