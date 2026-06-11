"""Tests for the library locator in pysteamnet._loader.

These exercise the search logic WITHOUT any real Steam binary on disk: we
monkeypatch os.path.isfile and ctypes.CDLL so the loader believes (or
disbelieves) in files we name, and records the path it would have loaded.

CAUTION: load_library() caches its result in the module global
_loader._lib. Every test here resets that global around itself (the
reset_lib fixture) so a half-loaded state never leaks into other test
files when the whole suite runs together.
"""

import ctypes
import os
import sys

import pytest

from pysteamnet import _loader
from pysteamnet._loader import SteamLibraryNotFoundError


@pytest.fixture(autouse=True)
def reset_lib():
    """Force _loader._lib to None for the test, then restore the original.

    autouse so every test in this file starts from "nothing loaded" and
    leaves the global exactly as it found it -- the loader's cache must
    not poison test_guards or any live test that loads the real binary.
    """
    saved = _loader._lib
    _loader._lib = None
    try:
        yield
    finally:
        _loader._lib = saved


# ===========================================================================
# library_filename(): the right name per platform
# ===========================================================================

def test_library_filename_current_platform():
    name = _loader.library_filename()
    if sys.platform == "darwin":
        assert name == "libsteam_api.dylib"
    elif sys.platform.startswith(("linux", "freebsd")):
        assert name == "libsteam_api.so"
    elif sys.platform == "win32":
        assert name == "steam_api64.dll"
    else:  # pragma: no cover -- the platform the CI box actually is decides this
        pytest.skip(f"untested platform {sys.platform!r}")


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("darwin", "libsteam_api.dylib"),
        ("linux", "libsteam_api.so"),
        ("win32", "steam_api64.dll"),
    ],
)
def test_library_filename_each_platform(monkeypatch, platform, expected):
    # Pretend to be each OS in turn so all three branches are covered
    # regardless of which machine runs the suite.
    monkeypatch.setattr(sys, "platform", platform)
    assert _loader.library_filename() == expected


def test_library_filename_unknown_platform_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "plan9")
    with pytest.raises(SteamLibraryNotFoundError):
        _loader.library_filename()


# ===========================================================================
# _candidate_paths(): the documented search ORDER
# ===========================================================================

def test_candidate_order_explicit_then_env_then_package_then_cwd(monkeypatch):
    filename = _loader.library_filename()
    monkeypatch.setenv("PYSTEAMNET_LIBSTEAM_API", "/env/dir")

    candidates = list(_loader._candidate_paths("/explicit/dir"))

    # Four sources, in this exact order.
    assert len(candidates) == 4
    explicit, env, package, cwd = candidates

    # 1. explicit arg (a directory -> filename appended)
    assert explicit == os.path.join("/explicit/dir", filename)
    # 2. env var (a directory -> filename appended)
    assert env == os.path.join("/env/dir", filename)
    # 3. the installed package directory
    assert package == os.path.join(os.path.dirname(os.path.abspath(_loader.__file__)), filename)
    # 4. the current working directory
    assert cwd == os.path.join(os.getcwd(), filename)


def test_candidate_no_explicit_no_env_yields_two(monkeypatch):
    # With neither an explicit path nor the env var, only package-dir and
    # cwd remain -- and in that order.
    filename = _loader.library_filename()
    monkeypatch.delenv("PYSTEAMNET_LIBSTEAM_API", raising=False)

    candidates = list(_loader._candidate_paths(None))

    assert len(candidates) == 2
    package, cwd = candidates
    assert package == os.path.join(os.path.dirname(os.path.abspath(_loader.__file__)), filename)
    assert cwd == os.path.join(os.getcwd(), filename)


def test_candidate_directory_arg_gets_filename_appended(monkeypatch):
    monkeypatch.delenv("PYSTEAMNET_LIBSTEAM_API", raising=False)
    filename = _loader.library_filename()

    # A directory does NOT end in the filename, so the loader appends it.
    first = next(iter(_loader._candidate_paths("/some/sdk/dir")))
    assert first == os.path.join("/some/sdk/dir", filename)


def test_candidate_file_arg_passes_through(monkeypatch):
    monkeypatch.delenv("PYSTEAMNET_LIBSTEAM_API", raising=False)
    filename = _loader.library_filename()

    # A path whose basename IS the filename is treated as the file itself
    # and used verbatim -- not "dir/filename/filename".
    full = os.path.join("/some/sdk/dir", filename)
    first = next(iter(_loader._candidate_paths(full)))
    assert first == full


def test_candidate_env_file_arg_passes_through(monkeypatch):
    # Same file-vs-directory rule applies to the env var.
    filename = _loader.library_filename()
    full = os.path.join("/env/place", filename)
    monkeypatch.setenv("PYSTEAMNET_LIBSTEAM_API", full)

    candidates = list(_loader._candidate_paths(None))
    # First candidate is the env var (no explicit arg), used verbatim.
    assert candidates[0] == full


# ===========================================================================
# load_library(): failure lists every place it looked
# ===========================================================================

def test_load_library_failure_lists_all_candidates(monkeypatch):
    monkeypatch.setenv("PYSTEAMNET_LIBSTEAM_API", "/env/dir")
    # Nothing exists anywhere.
    monkeypatch.setattr(os.path, "isfile", lambda p: False)

    with pytest.raises(SteamLibraryNotFoundError) as excinfo:
        _loader.load_library("/explicit/dir")

    msg = str(excinfo.value)
    filename = _loader.library_filename()
    # Every searched location appears in the message, plus the SDK pointer.
    assert os.path.join("/explicit/dir", filename) in msg
    assert os.path.join("/env/dir", filename) in msg
    assert os.path.join(os.getcwd(), filename) in msg
    assert "partner.steamgames.com" in msg


# ===========================================================================
# load_library(): success loads the first existing file and caches it
# ===========================================================================

class _StubCDLL:
    """Records the path it was constructed with, so the test can inspect it."""

    instances = []

    def __init__(self, path):
        self.path = path
        _StubCDLL.instances.append(self)


def test_load_library_success_loads_first_match_and_caches(monkeypatch):
    _StubCDLL.instances.clear()
    filename = _loader.library_filename()
    monkeypatch.delenv("PYSTEAMNET_LIBSTEAM_API", raising=False)

    # Only the cwd candidate "exists" (package dir does not).
    wanted = os.path.join(os.getcwd(), filename)
    monkeypatch.setattr(os.path, "isfile", lambda p: p == wanted)
    monkeypatch.setattr(ctypes, "CDLL", _StubCDLL)

    handle = _loader.load_library()
    assert isinstance(handle, _StubCDLL)
    assert handle.path == wanted
    # The handle is cached: a second call returns the SAME object and does
    # NOT construct another CDLL (ignores the path arg, per the docstring).
    again = _loader.load_library("/ignored/now")
    assert again is handle
    assert len(_StubCDLL.instances) == 1


def test_load_library_explicit_path_wins(monkeypatch):
    _StubCDLL.instances.clear()
    filename = _loader.library_filename()
    monkeypatch.setenv("PYSTEAMNET_LIBSTEAM_API", "/env/dir")

    explicit = os.path.join("/explicit/dir", filename)
    env = os.path.join("/env/dir", filename)
    # BOTH explicit and env "exist"; the explicit one must be chosen first.
    monkeypatch.setattr(os.path, "isfile", lambda p: p in (explicit, env))
    monkeypatch.setattr(ctypes, "CDLL", _StubCDLL)

    handle = _loader.load_library("/explicit/dir")
    assert handle.path == explicit


# ===========================================================================
# get_lib(): a clear error when nothing is loaded
# ===========================================================================

def test_get_lib_unloaded_raises_runtimeerror():
    # reset_lib guarantees _lib is None here.
    with pytest.raises(RuntimeError) as excinfo:
        _loader.get_lib()
    # The message must name the function the caller forgot to call.
    assert "load_steam_api" in str(excinfo.value)


def test_get_lib_returns_loaded_handle():
    sentinel = object()
    _loader._lib = sentinel  # restored by reset_lib's finally
    assert _loader.get_lib() is sentinel
