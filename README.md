# pysteamnet

A faithful, pure-`ctypes` Python mapping of the Steamworks SDK's **flat C
API**. No compiled shim, no C++, no build step, zero runtime
dependencies: Python talks directly to Valve's own shipped binary
(`steam_api64.dll` / `libsteam_api.so` / `libsteam_api.dylib`) through
`ctypes` from the standard library. By talking straight to the flat C
API in Valve's own shipped binary, there is no intermediate layer to
maintain at all.

> **Naming note.** The import name is `pysteamnet` (one word). It is
> distinct from the unrelated Rust-based `py_steam_net` project; the
> near-collision is a coincidence, not a fork.

## The design law

This module is **simply a faithful mapping of Valve's flat C API into
Python**, and that one idea decides everything:

- **Names mirror Valve exactly.** Every bound function keeps its flat-C
  name — `SteamAPI_ISteamMatchmaking_CreateLobby`,
  `SteamAPI_ISteamNetworkingMessages_SendMessageToUser`, and so on. With
  Valve's docs open you need zero translation.
- **No invented abstractions.** No transport classes, no event
  framework, no "helpful" renaming, no game logic. Just the flat API.
- **Poll-only manual dispatch.** Callbacks are drained from a queue once
  per frame, on your own thread. No foreign Steam thread ever calls into
  Python — which is exactly why a pure-`ctypes` binding can work at all.
- **Only the needed slice is bound, growing as needed.** Today that is
  init/shutdown, the dispatch pump, `ISteamMatchmaking` (lobbies,
  invites), `ISteamNetworkingMessages` (transport), and a minimal
  `ISteamFriends` / `ISteamUtils` / `ISteamUser`.

The main names with **no** flat-C equivalent are the necessary Python
plumbing, and nothing more:

- `load_steam_api()` — the `ctypes` bootstrap (find, load, type-check the
  binary).
- `run_frame()` / `take_call_result()` — the manual-dispatch loop,
  returned as plain data instead of a framework.
- `ReceivedMessage` — the safe, copied snapshot
  `ReceiveMessagesOnChannel` returns instead of foreign memory.

(Plus a few supporting exports of the same character: the loader's
`SteamLibraryNotFoundError` and `library_filename()`, and the
introspection tables `FLAT_SIGNATURES` and `CALLBACK_REGISTRY` the test
suite is built on.) Everything else is Valve's API, name for name.

## Install

There is nothing to compile.

```bash
pip install -e .
```

Requires Python **>= 3.11**. The only runtime requirement is `ctypes`,
which ships with CPython.

## Get the SDK and place the binary

The Steamworks binary is Valve's own shipped library — the same file
every Steam game redistributes. It is **never committed to this
repository** (`.gitignore` enforces that). You download it yourself:

1. Get the Steamworks SDK (free) from
   <https://partner.steamgames.com/doc/sdk>. pysteamnet is pinned to
   **SDK v1.64**.
2. Copy the library for your platform out of the unpacked SDK:

   | OS      | Source path in the SDK                          |
   | ------- | ----------------------------------------------- |
   | macOS   | `sdk/redistributable_bin/osx/libsteam_api.dylib` |
   | Linux   | `sdk/redistributable_bin/linux64/libsteam_api.so` |
   | Windows | `sdk/redistributable_bin/win64/steam_api64.dll`  |

3. Put it where the loader can find it. The search order is (first hit
   wins):

   1. an explicit path you pass to `load_steam_api(path)` (a file, or a
      directory containing it);
   2. the `PYSTEAMNET_LIBSTEAM_API` environment variable (a file or a
      directory);
   3. the `pysteamnet` package directory;
   4. the current working directory.

If the library can't be found, `load_steam_api()` raises
`SteamLibraryNotFoundError` whose message lists every location it tried,
so the fix is visible in the traceback itself.

During development the simplest move is to point the environment variable
straight at the SDK's redistributable directory:

```bash
export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx
```

## The development loop

You do **not** need a Steam partner account to develop against this
library. Valve's test app **Spacewar, AppID 480**, is usable by anyone:

1. Have the Steam client installed, running, and logged in.
2. Create a `steam_appid.txt` containing the single line `480` in the
   working directory you run from (`echo 480 > steam_appid.txt` — the
   file is deliberately gitignored, so a fresh clone won't have one).
   This is a development-only convenience — it tells Steam which
   app you are, and it lets `SteamAPI_RestartAppIfNecessary` skip the
   relaunch.
3. `SteamAPI_InitFlat` should succeed, and the first smoke test is
   printing your own persona name.

Shipped game builds launch **through** Steam instead and must **not**
carry `steam_appid.txt`.

## Quickstart

This is the same five-minute tour that lives at the top of
`src/pysteamnet/__init__.py` — copied verbatim so the two never drift
apart.

```python
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
```

## API conventions

A few small, consistent rules apply across the whole binding.

**Interface pointers are explicit first arguments.** The flat C API
passes `ISteamWhatever* self` as the first argument of every interface
call, and so do we. You get the pointer from the **versioned accessor**
and hand it back in:

```c
/* C */
ISteamMatchmaking *mm = SteamAPI_SteamMatchmaking_v009();
SteamAPI_ISteamMatchmaking_CreateLobby(mm, k_ELobbyTypeFriendsOnly, 4);
```

```python
# Python — identical shape
mm = pysteamnet.SteamAPI_SteamMatchmaking_v009()
pysteamnet.SteamAPI_ISteamMatchmaking_CreateLobby(mm, pysteamnet.k_ELobbyTypeFriendsOnly, 4)
```

The pointer is an opaque token (`c_void_p`); it is never dereferenced in
Python.

**Enums are `IntEnum`s with Valve's exact member names.** They are also
re-exported flat, so you can write `pysteamnet.k_ELobbyTypeFriendsOnly`
or `pysteamnet.k_ESteamAPIInitResult_OK` directly, just like the C
constant.

**Text params are `str`; payloads are `bytes`.** String arguments take a
Python `str` and are UTF-8 encoded for you; string returns are decoded
back to `str`. Wire payloads (lobby chat, networking messages) are
`bytes` in and out — and you pass the buffer, not a length: pysteamnet
fills the `cubData`/`cubMsgBody` length from `len()` so the length can
never disagree with the buffer (the classic FFI bug).

**Two layers of validation.** First, `ctypes` `argtypes` reject
wrong C types — the runtime equivalent of C's compile-time checking.
Second, friendly preflight guards check ranges, flags, and types before
the call and raise with a teaching error message (often including the
recipe to build the right value).

**The async pattern.** Calls like `CreateLobby`, `JoinLobby`, and
`RequestLobbyList` return immediately with a `SteamAPICall_t` handle; the
real result arrives later. Pump the dispatch loop and collect it:

```python
call = pysteamnet.SteamAPI_ISteamMatchmaking_CreateLobby(mm, pysteamnet.k_ELobbyTypeFriendsOnly, 4)
while (result := pysteamnet.take_call_result(call)) is None:
    pysteamnet.run_frame(pipe)
    time.sleep(1 / 60)
callback_id, payload, io_failed = result   # e.g. 513 == LobbyCreated_t
```

Broadcast callbacks (lobby joins, persona changes, session requests, and
so on) are not keyed to a handle — they simply appear in the
`(callback_id, payload)` list that `run_frame()` returns each frame.

## Pinned SDK

pysteamnet is developed and verified against a single SDK version. The
versioned accessors below are the compatibility contract; the `_vNNN`
suffix is deliberately visible at every call site.

| Item                | Value                                            |
| ------------------- | ------------------------------------------------ |
| Steamworks SDK      | **v1.64**                                         |
| `ISteamUser`        | `SteamAPI_SteamUser_v023()`                       |
| `ISteamFriends`     | `SteamAPI_SteamFriends_v018()`                    |
| `ISteamUtils`       | `SteamAPI_SteamUtils_v010()`                       |
| `ISteamMatchmaking` | `SteamAPI_SteamMatchmaking_v009()`                |
| `ISteamNetworkingMessages` | `SteamAPI_SteamNetworkingMessages_SteamAPI_v002()` |

If you upgrade the SDK, re-verify these accessor symbols against the new
header and re-run the struct-layout tests — callback struct packing and
accessor versions are exactly the things that move between SDK releases.

## Testing

Tests come in three tiers, gated by pytest markers (registered in
`pyproject.toml`): `sdk` needs the unpacked SDK on disk (set
`PYSTEAMNET_SDK` to its root), and `steam` needs a running, logged-in
Steam client plus a `steam_appid.txt` containing `480` in the working
directory.

```bash
# Pure and hermetic — struct layouts/sizes, signature declarations,
# and the pump driven against a scripted fake. No SDK, no Steam.
python -m pytest -m "not sdk and not steam"

# Adds the cross-check of FLAT_SIGNATURES against Valve's own
# steam_api.json shipped in the SDK.
PYSTEAMNET_SDK=~/Downloads/sdk python -m pytest -m "not steam"

# Everything, including live calls against a running Steam client.
python -m pytest
```

For the full end-to-end acceptance runs — lobby create/join/invite
between two accounts, and `ISteamNetworkingMessages` send/receive between
two machines — see the scripts under `examples/`. Those need two real
Steam logins (and, for the transport, two machines), so they live as
runnable examples rather than automated tests.

## Troubleshooting

**`SteamLibraryNotFoundError` on `load_steam_api()`.** The binary isn't
on the search path. The error message lists every location that was
tried; copy `libsteam_api.dylib` / `.so` / `steam_api64.dll` out of the
SDK into one of them, or set `PYSTEAMNET_LIBSTEAM_API`.

**`SteamAPI_InitFlat` returns `2` (NoSteamClient).** Steam isn't running,
or you aren't logged in. Start the Steam client and sign in.

**`SteamAPI_InitFlat` returns `3` (VersionMismatch).** The Steam client
is older than the SDK this is built against. Update the Steam client.

**`SteamAPI_InitFlat` returns `1` (FailedGeneric).** Usually a missing
`steam_appid.txt` (containing `480`) in the working directory during
development. Always pass a `SteamErrMsg()` buffer to `InitFlat` and print
its text — it explains the specific failure:

```python
err = pysteamnet.SteamErrMsg()
if pysteamnet.SteamAPI_InitFlat(err) != pysteamnet.k_ESteamAPIInitResult_OK:
    print(err.value.decode("utf-8", "replace"))
```

**A guard raises `TypeError` saying it wanted `bytes`.** String fields
take `str` (encoded for you); wire payloads take `bytes`. If you have a
`str` payload, encode it first: `msg.encode("utf-8")`.

**Invite dialog silently does nothing.** Overlay-dependent calls — most
visibly `ActivateGameOverlayInviteDialog` — need the Steam overlay, which
injects into a real game's renderer. A plain Python script reports
`IsOverlayEnabled() == False`, and the dialog simply won't open. This is
expected outside an actual game process; the underlying
`InviteUserToLobby` path still works.

## Scope and roadmap

The bound surface grows only as it is needed. Deliberately **out** until
a concrete need arrives: achievements, stats, Steam Cloud, Workshop,
Steam Input, and the lower-level `ISteamNetworkingSockets` (the
message-based `ISteamNetworkingMessages` is the transport we use).

This library serves a co-op game built by the author and his son, but it
stays strictly **game-agnostic**: the game keeps its own transport
adapter on its own side, sitting on top of `ISteamNetworkingMessages`.
pysteamnet itself holds no game logic and no opinions — it is the flat C
API, faithfully, and that is all it ever intends to be.

## License

To be determined before any public release.
