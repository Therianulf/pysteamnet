# pySteamNet

A pure-Python binding to the Steamworks SDK's **flat C API**, built with
`ctypes` and nothing else. No compiled shim, no C++, no build step:
Python talks directly to Valve's own shipped binary
(`steam_api64.dll` / `libsteam_api.so` / `libsteam_api.dylib`).

Ben (a distributed systems engineer) is the architect and reviews all
work; he handles ALL git operations — **never run git commands**. This
repo is a sibling of `~/Github/BjornsGame` ("Bjorn's World"), the game
that needs it: internet co-op between a father and his son who lives in
another state most of the year, with an eventual public Steam release.
This module may be open-sourced someday — write it like strangers will
read it.

## The design law: a flat C mapping, nothing more

This module is **simply a faithful mapping of Valve's flat C API into
Python**. That single idea decides every design question:

- **Mirror Valve's names exactly** at the binding layer:
  `SteamAPI_ISteamMatchmaking_CreateLobby`,
  `SteamAPI_ISteamNetworkingMessages_SendMessageToUser`, etc. A reader
  with Valve's docs open should need zero translation.
- **No opinions, no game logic, no invented abstractions.** No transport
  classes, no event frameworks, no "helpful" renaming. Ergonomic wrappers,
  if ever wanted, live in a clearly separated optional module — or better,
  in the consuming game. (Bjorn's World keeps its transport adapter on its
  own side; this repo stays game-agnostic.)
- **`ctypes` from the standard library only. Zero dependencies, forever.**
  No cffi, no compiled extension, nothing to build on any platform. If a
  dependency ever seems necessary, ask Ben first.
- **Bind only the slice we need, growing as needed.** Not the whole SDK.
  Initial surface: init/shutdown, the manual-dispatch callback pump,
  `ISteamMatchmaking` (lobbies/invites), `ISteamNetworkingMessages`
  (transport), minimal `ISteamFriends` (persona name, rich presence) and
  `ISteamUtils`. Explicitly out until needed: achievements, stats, cloud,
  workshop, input, everything else.

Why this exists (ecosystem survey, verified 2026-06-10): Python has no
cared-for Steamworks binding. SteamworksPy is stale (pinned ~SDK 1.51,
2021) and rots precisely because it routes through a hand-maintained
compiled C++ shim; py_steam_net (note the near-name-collision — if we
open-source, consider the naming) is a tiny Rust-based project. The
direct-to-flat-C approach removes the layer that rots.

## Verified technical foundation (2026-06-10, sources on file in
BjornsGame/.claude/memory/)

- **The flat API is complete for our needs.** `steam_api_flat.h` exposes
  plain-C-linkage mirrors of every interface — including
  `ISteamNetworkingSockets`, `ISteamNetworkingMessages`, and
  `ISteamMatchmaking` — all exported by the `steam_api[64]` binary.
  (Beware: old header *snapshots* in third-party repos predate the
  networking interfaces; always work from a current SDK's header.)
- **`steam_api.json`** ships in the SDK (`public/steam/`): a
  machine-readable description of (almost) the whole flat API, intended
  for binding generators. Start by hand-declaring the needed functions'
  `argtypes`/`restype`; a generator over the JSON is a later option.
- **Manual dispatch is the callback mechanism** (SDK ≥ 1.48, built by
  Valve expressly for non-C++ binding layers). The pump must follow spec
  EXACTLY — this is the known hard 20%, unproven in published Python code
  (proven in Rust/C#/Lua):
  1. `SteamAPI_ManualDispatch_Init()` once, around init.
  2. Per frame: `SteamAPI_ManualDispatch_RunFrame(pipe)`, then loop
     `SteamAPI_ManualDispatch_GetNextCallback(pipe, &msg)` → handle →
     `SteamAPI_ManualDispatch_FreeLastCallback(pipe)` (ALWAYS free, even
     on unknown callbacks).
  3. Async call-results: when the callback is `SteamAPICallCompleted_t`,
     allocate the stated buffer and call
     `SteamAPI_ManualDispatch_GetAPICallResult(...)`.
  - The pipe comes from `SteamAPI_GetHSteamPipe()`.
  - Ordering mistakes here have caused real-world breakage in mature
    bindings (see Steamworks.NET issue #413) — implement from Valve's
    docs, not from memory.
- **Poll-only by design is a gift to Python:** with manual dispatch, no
  foreign thread ever calls into Python. The game pumps the dispatch loop
  once per frame from its own main loop. No GIL games, no thread
  marshalling.
- **Known sharp edges to handle deliberately:**
  - `CSteamID` / `CGameID` are packed 64-bit values — treat as
    `ctypes.c_uint64` end to end.
  - Callback structs use platform-dependent packing (Steam packs
    differently on Windows vs Linux/macOS). Verify each struct's layout
    per platform against the SDK headers — do not assume default ctypes
    alignment. Get struct sizes asserted in tests.
  - Interface accessors are **versioned** (e.g.
    `SteamAPI_SteamMatchmaking_v009()`). Pin to the SDK version we
    develop against and record it in this file when chosen.
  - The exact init symbol varies by SDK era (`SteamAPI_Init` returning
    bool vs newer `SteamAPI_InitFlat(&errMsg)`); check the downloaded
    SDK's header rather than assuming.
- **Distribution facts:** redistributing `steam_api64.dll` /
  `libsteam_api.so` / `.dylib` with a shipped game is Valve's documented
  standard practice. The SDK itself comes from
  partner.steamgames.com/doc/sdk (free download). The SDK binaries do
  NOT get committed to this repo — document where to place them instead.

## Pinned SDK & resolved symbols (SDK v1.64, verified live 2026-06-10)

Everything below was verified against the downloaded SDK on disk AND
against the running Steam client on macOS arm64. Re-verify this whole
block (and re-run the layout tests) before bumping the SDK.

- **Pinned SDK: v1.64** (`steamworks_sdk_164.zip`, changelog dated
  11 Mar 2026). Local dev copy unpacked at `~/Downloads/sdk` (never
  committed). Tier-B tests find it via `PYSTEAMNET_SDK`.
- **Init symbol:** `SteamAPI_InitFlat(SteamErrMsg*) -> ESteamAPIInitResult`.
  The `SteamAPI_Init`/`SteamAPI_InitEx` from Valve's C++ examples are
  header-inline only and DO NOT exist in the binary.
- **Accessor versions (the compatibility pins):**
  `SteamAPI_SteamUser_v023`, `SteamAPI_SteamFriends_v018`,
  `SteamAPI_SteamUtils_v010`, `SteamAPI_SteamMatchmaking_v009`,
  `SteamAPI_SteamNetworkingMessages_SteamAPI_v002` (note the
  `_SteamAPI_` infix on the networking accessor).
- **Callback IDs we decode** (`CALLBACK_REGISTRY` in `_structs.py`):
  PersonaStateChange_t 304, GameLobbyJoinRequested_t 333,
  LobbyInvite_t 503, LobbyEnter_t 504, LobbyDataUpdate_t 505,
  LobbyChatUpdate_t 506, LobbyChatMsg_t 507, LobbyMatchList_t 510,
  LobbyCreated_t 513, SessionRequest_t 1251, SessionFailed_t 1252.
  SteamAPICallCompleted_t is 703 and is consumed by the pump itself.
- **Packing (the silent-corruption hazard):** ordinary callback structs
  are `pack(4)` on macOS/Linux/FreeBSD and `pack(8)` on Windows
  (steamclientpublic.h:1143). EXCEPTIONS, same on all platforms:
  `SteamNetworkingIdentity` (136 B) and the two NetworkingMessages
  session callbacks are `pack(1)`; `SteamNetworkingMessage_t` is
  natural-aligned; `SteamNetConnectionInfo_t` (696 B) is defined under
  the platform pack region but Valve padded it explicitly, so its
  layout is identical under pack 1/4/8 (compiler-verified) and we
  declare it pack(1). `_pack_` is therefore set per struct, never
  globally. All sizes are assert-tested.
- **Manual-dispatch gotcha, now load-bearing knowledge:** the pump
  pseudocode comment in `steam_api.h` (~line 177) is GARBLED (truncated
  cast, references a variable that doesn't exist). The correct call is
  `GetAPICallResult(pipe, inner.m_hAsyncCall, buf, inner.m_cubParam,
  inner.m_iCallback, &failed)` using the INNER `SteamAPICallCompleted_t`
  fields — never the outer message's id (703). Our pump also runs
  `FreeLastCallback` in a `finally`, so unknown callbacks and decode
  errors can never leak the slot (the Steamworks.NET #413 failure class).
- **Library loading:** `load_steam_api()` searches explicit path →
  `PYSTEAMNET_LIBSTEAM_API` env (file or dir) → package dir → cwd.
  Per-OS names: `libsteam_api.dylib` / `libsteam_api.so` /
  `steam_api64.dll`. The v1.64 macOS dylib is universal (arm64+x86_64),
  so arm64 Python loads it natively.
- **Milestones verified live (2026-06-10):** M0 (init + persona name),
  M1 (pump delivered a real `LobbyMatchList_t` call-result; unknown
  callbacks delivered as bytes and freed), M2 single-account (create
  lobby, data round-trip, chat echo, leave). Still pending Ben's
  two-account/two-machine acceptance: lobby invite/join across machines
  (M2) and `messages_pingpong.py` (M3).
- **Open for Ben:** license choice (pyproject placeholder says TBD);
  whether to ever generate declarations from `steam_api.json` (tests
  already cross-check against it).

## The development loop (no partner account needed)

Valve's test app **Spacewar, AppID 480**, is usable by anyone:

1. Steam client installed, running, and logged in.
2. A `steam_appid.txt` containing `480` next to the test script (dev
   only — shipped builds launch through Steam instead).
3. `SteamAPI_Init` succeeds → first smoke test is printing your own
   persona name via `ISteamFriends.GetPersonaName`.

Integration tests require a running Steam client and are marked as such;
pure-Python tests (struct layouts/sizes, signature declarations, pump
logic against a fake) must run without Steam.

## Roadmap

- **M0 — hello steam:** repo scaffold (pyproject, stdlib-only), SDK
  download documented, library located + loaded via `ctypes.CDLL`, init
  against AppID 480, persona name printed. Record the pinned SDK version
  here.
- **M1 — the pump:** manual-dispatch loop + a small registry mapping
  callback IDs → ctypes structs for just the callbacks we need. This is
  the hard milestone; budget care, write layout-assertion tests.
- **M2 — lobbies:** `ISteamMatchmaking` create/join/list/leave, lobby
  data, invites — end to end on AppID 480 between two accounts.
- **M3 — messages:** `ISteamNetworkingMessages` send/receive between two
  machines (this is the transport Bjorn's World's adapter will sit on).
- **M4 — consumption:** pip-installable (`pip install -e
  ../pySteamNet` from the game repo); Bjorn's World plugs it in behind
  its transport seam. Adding it to the game is Ben's dependency call.

## Working agreement

- Never run git commands; Ben commits.
- Zero runtime dependencies — `ctypes` and the standard library, period.
- Comment clearly in plain language (the sibling game repo is a teaching
  artifact for a kid who will grow up reading this code family; this repo
  is the systems tool of the family — professional, but never cryptic).
- Facts in this file were verified against partner.steamgames.com docs,
  PyPI, and the steamworks-rs / Steamworks.NET sources on 2026-06-10;
  re-verify against the actual downloaded SDK before relying on exact
  symbol names.
