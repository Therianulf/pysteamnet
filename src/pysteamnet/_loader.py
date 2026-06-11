"""Find and load Valve's Steamworks shared library with ctypes.

This module owns exactly one job: locating the Steam API binary on disk
and loading it via ctypes.CDLL. It knows nothing about the functions
inside that binary -- declaring those is _bindings.py's job.

The binary is Valve's own shipped library (the same file every Steam
game redistributes). It is NEVER committed to this repository. You get
it from the Steamworks SDK -- a free download at
https://partner.steamgames.com/doc/sdk -- under:

    sdk/redistributable_bin/osx/libsteam_api.dylib      (macOS)
    sdk/redistributable_bin/linux64/libsteam_api.so     (Linux)
    sdk/redistributable_bin/win64/steam_api64.dll       (Windows)

The search order (first hit wins) is documented on load_library() below.
"""

import ctypes
import os
import sys


class SteamLibraryNotFoundError(OSError):
    """Raised when the Steam API library cannot be found anywhere.

    The error message lists every location that was searched, so the fix
    is always visible in the traceback itself.
    """


# The loaded library handle, cached so every part of pysteamnet talks to
# the same CDLL instance. Loading twice would re-stamp signatures
# harmlessly, but one shared handle is simpler to reason about.
_lib = None


def library_filename():
    """Return the Steam API library's filename for this platform.

    Valve names the binary differently per OS; this is the exact name
    load_library() searches for. We target 64-bit everywhere (Steam
    itself dropped 32-bit support).
    """
    if sys.platform == "darwin":
        return "libsteam_api.dylib"
    if sys.platform.startswith(("linux", "freebsd")):
        return "libsteam_api.so"
    if sys.platform == "win32":
        return "steam_api64.dll"
    raise SteamLibraryNotFoundError(
        f"pysteamnet does not know the Steam library name for platform "
        f"{sys.platform!r}. Steam supports Windows, macOS, and Linux."
    )


def _candidate_paths(path):
    """Yield every location to try, in documented search order."""
    filename = library_filename()

    # 1. An explicit path argument always wins. It may point at the file
    #    itself or at a directory containing it.
    if path is not None:
        path = os.fspath(path)
        yield path if os.path.basename(path) == filename else os.path.join(path, filename)

    # 2. The PYSTEAMNET_LIBSTEAM_API environment variable -- a deployment
    #    override that needs no code changes. File or directory, as above.
    env = os.environ.get("PYSTEAMNET_LIBSTEAM_API")
    if env:
        yield env if os.path.basename(env) == filename else os.path.join(env, filename)

    # 3. Next to this package -- supports dropping the binary alongside
    #    an installed copy of pysteamnet.
    yield os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

    # 4. The current working directory -- mirrors Valve's own convention
    #    of shipping the binary next to the game executable, and is the
    #    natural spot during development (same place as steam_appid.txt).
    yield os.path.join(os.getcwd(), filename)


def load_library(path=None):
    """Locate and ctypes.CDLL the Steam API library; return the handle.

    Search order (first existing file wins):
      1. the explicit ``path`` argument (file, or directory containing it)
      2. the ``PYSTEAMNET_LIBSTEAM_API`` environment variable (file or dir)
      3. the pysteamnet package directory
      4. the current working directory

    Idempotent: once loaded, the cached handle is returned and the
    ``path`` argument is ignored. Plain CDLL (cdecl) is correct on every
    platform -- Valve's exports use S_CALLTYPE, which is __cdecl on
    Windows and empty elsewhere (steam_api_common.h).
    """
    global _lib
    if _lib is not None:
        return _lib

    tried = []
    for candidate in _candidate_paths(path):
        tried.append(candidate)
        if os.path.isfile(candidate):
            _lib = ctypes.CDLL(candidate)
            return _lib

    locations = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(tried))
    raise SteamLibraryNotFoundError(
        f"Could not find {library_filename()!r}. Searched, in order:\n"
        f"{locations}\n"
        f"The Steamworks binary is never committed to this repository. "
        f"Download the SDK from https://partner.steamgames.com/doc/sdk "
        f"and copy the library from sdk/redistributable_bin/ to one of "
        f"the locations above, or set PYSTEAMNET_LIBSTEAM_API."
    )


def get_lib():
    """Return the loaded library handle, or raise with the fix spelled out.

    Every bound function calls this first, so forgetting to initialize
    produces one clear sentence instead of an AttributeError.
    """
    if _lib is None:
        raise RuntimeError(
            "The Steam API library is not loaded yet. Call "
            "pysteamnet.load_steam_api() once, before any other Steam call."
        )
    return _lib
