"""Structural tests over the binding table and the callback registry.

These never touch Steam or ctypes calls -- they read the static FLAT_SIGNATURES
table and CALLBACK_REGISTRY and assert the binding layer is internally
consistent and obeys its own naming law:

  * Every signature is well-formed (a list of real ctypes types, a sane
    restype).
  * Every bound C symbol has a matching public Python wrapper of the exact
    same name -- the "faithful flat mapping" promise.
  * Every name starts with "SteamAPI_" (the flat-API invariant).
  * The five versioned interface accessors we pinned to SDK v1.64 are present.
  * The callback registry's keys agree with each struct's own k_iCallback,
    and the set of callbacks we decode is exactly the slice we intend to.

If any of these drift (a wrapper renamed, a signature half-edited, a new
callback added without registering it), one of these fails fast.
"""

import ctypes

import pytest

import pysteamnet as steam
from pysteamnet import FLAT_SIGNATURES, CALLBACK_REGISTRY


# The interface accessors we pinned for SDK v1.64. If Valve bumps an
# interface version we must consciously re-pin -- this list makes that a
# deliberate, test-visible change rather than a silent one.
PINNED_ACCESSORS = [
    "SteamAPI_SteamUser_v023",
    "SteamAPI_SteamFriends_v018",
    "SteamAPI_SteamUtils_v010",
    "SteamAPI_SteamMatchmaking_v009",
    "SteamAPI_SteamNetworkingMessages_SteamAPI_v002",
]

# The complete set of callbacks the pump knows how to decode. Adding or
# removing one is a real change to the binding's surface, so it is spelled
# out here and checked exactly.
EXPECTED_CALLBACK_IDS = {304, 333, 503, 504, 505, 506, 507, 510, 513, 1251, 1252}


def _is_ctypes_type(obj):
    """True if obj is a ctypes type usable as an argtype/restype.

    ctypes' own types (c_int, POINTER(...), Structure subclasses, ...) are
    all instances of ctypes._SimpleCData / Structure metaclasses; the
    reliable, version-proof check is "does ctypes.sizeof accept it?".
    """
    try:
        ctypes.sizeof(obj)
        return True
    except TypeError:
        return False


# ===========================================================================
# Every signature entry is well-formed.
# ===========================================================================

def test_flat_signatures_is_nonempty():
    assert len(FLAT_SIGNATURES) >= 50  # the binding's documented ~57-symbol slice


@pytest.mark.parametrize("name", sorted(FLAT_SIGNATURES))
def test_signature_argtypes_is_clean_list(name):
    argtypes, _restype = FLAT_SIGNATURES[name]
    # argtypes is always a list (possibly empty for nullary C functions)...
    assert isinstance(argtypes, list), f"{name}: argtypes must be a list"
    # ...with no None holes -- a None argtype means a half-finished edit.
    assert all(a is not None for a in argtypes), f"{name}: argtypes has a None element"
    # ...and every element is a real ctypes type.
    for a in argtypes:
        assert _is_ctypes_type(a), f"{name}: argtype {a!r} is not a ctypes type"


@pytest.mark.parametrize("name", sorted(FLAT_SIGNATURES))
def test_signature_restype_is_void_or_ctypes(name):
    _argtypes, restype = FLAT_SIGNATURES[name]
    # restype is either None (C void) or a real ctypes type. Nothing else.
    assert restype is None or _is_ctypes_type(restype), (
        f"{name}: restype {restype!r} must be None (void) or a ctypes type"
    )


# ===========================================================================
# The flat-mapping promise: name law + a wrapper for every symbol.
# ===========================================================================

@pytest.mark.parametrize("name", sorted(FLAT_SIGNATURES))
def test_every_signature_name_is_flat_api(name):
    assert name.startswith("SteamAPI_"), (
        f"{name}: every bound symbol must mirror a flat C export (SteamAPI_*)"
    )


@pytest.mark.parametrize("name", sorted(FLAT_SIGNATURES))
def test_every_signature_has_public_wrapper(name):
    # The whole design: the package namespace exposes a same-named callable
    # for every C symbol we bind. A missing one means the table and the
    # wrappers drifted apart.
    wrapper = getattr(steam, name, None)
    assert wrapper is not None, f"{name}: no public wrapper exported from pysteamnet"
    assert callable(wrapper), f"{name}: pysteamnet.{name} exists but is not callable"


def test_pinned_accessors_present():
    missing = [a for a in PINNED_ACCESSORS if a not in FLAT_SIGNATURES]
    assert not missing, f"pinned SDK v1.64 accessors missing from FLAT_SIGNATURES: {missing}"
    # And each is callable on the package, like any other wrapper.
    for a in PINNED_ACCESSORS:
        assert callable(getattr(steam, a, None)), f"{a}: not exported/callable"


# ===========================================================================
# The callback registry agrees with itself and with our intended slice.
# ===========================================================================

def test_callback_registry_keys_match_struct_ids():
    # Each registry key must equal the struct's own k_iCallback -- the
    # registry is built from that field, so a mismatch would mean a class
    # was registered under the wrong number.
    for cid, cls in CALLBACK_REGISTRY.items():
        assert cls.k_iCallback == cid, (
            f"registry key {cid} != {cls.__name__}.k_iCallback ({cls.k_iCallback})"
        )


def test_callback_registry_id_set_is_exactly_expected():
    assert set(CALLBACK_REGISTRY) == EXPECTED_CALLBACK_IDS


def test_callback_registry_values_are_distinct_structs():
    # No two ids should map to the same class (a copy/paste slip would do
    # that), so the number of distinct classes equals the number of ids.
    assert len(set(CALLBACK_REGISTRY.values())) == len(CALLBACK_REGISTRY)
