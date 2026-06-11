# pysteamnet examples

Small, runnable programs that exercise the binding against Valve's free
test app, **Spacewar (AppID 480)**. They use only the public `pysteamnet`
surface -- the same flat-C names Valve documents -- so each one doubles as
a worked example of the API it touches.

## Before you start

1. **Steam must be running and logged in** on each machine you run an
   example on. The binding talks to that local client.

2. **Put Valve's `steam_api` library where the loader can find it.** It is
   never committed to this repo. The simplest development setup is to point
   the loader straight at your unpacked SDK:

   ```sh
   # macOS (this repo's dev machine):
   export PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx
   # Linux:   .../redistributable_bin/linux64
   # Windows: .../redistributable_bin/win64
   ```

   (The loader also checks an explicit path argument, then the package
   directory, then the current directory -- see `_loader.py`.)

3. **Create `steam_appid.txt` containing just `480`** in the directory you
   run from (a fresh clone does not have one -- it is gitignored):

   ```sh
   echo 480 > steam_appid.txt
   ```

   Then **run every example from the repo root**, where you created it.
   This file is intentionally `.gitignore`d: it is a
   development-only convenience (it tells the Steam client to treat the
   script as Spacewar), and shipped games must launch through Steam
   instead, so it must never be committed.

## The examples

| script | demonstrates | accounts | machines | run command |
| --- | --- | --- | --- | --- |
| `hello_steam.py` | init / shutdown, persona name, your own SteamID | 1 | 1 | `python examples/hello_steam.py` |
| `pump_watch.py` | the manual-dispatch pump; prints every callback as it arrives | 1 | 1 | `python examples/pump_watch.py` |
| `lobby_host.py` | create a lobby, async call-result, member/data callbacks | 1 (+1 to see traffic) | 1 (+1 to join) | `python examples/lobby_host.py` |
| `lobby_join.py` | join a lobby, read lobby data + members, send chat | 1 (a 2nd account) | 1 (a 2nd machine) | `python examples/lobby_join.py <lobby_id>` |
| `messages_pingpong.py` | ISteamNetworkingMessages: reliable round-trips, sessions | 2 | 2 | `listen` on one, `connect <id>` on the other |

The "accounts" and "machines" columns are load-bearing. **Two logged-in
Steam clients cannot share one machine**, so any example that needs a
second account needs a second computer too -- a friend's PC, your other
machine, your kid's laptop. For lobbies and messaging, the two accounts
being Steam friends is the simplest way for the routing to find each other.

## Suggested order

Work up from "does anything work at all" to the full two-machine transport:

1. **`hello_steam.py`** -- proves the library loads, Steam connects, and
   you can read your own persona name and SteamID. One account, one
   machine. If this fails, nothing else will; fix it first. (It also prints
   your SteamID64, which the messaging demo needs.)
2. **`pump_watch.py`** -- proves the callback pump runs. One account, one
   machine; harmless to leave running while you poke at Steam.
3. **The lobby pair** -- run `lobby_host.py` on your machine, copy the
   lobby id it prints, and have a second account on a second machine run
   `lobby_join.py <id>`. Watch the host report the join.
4. **`messages_pingpong.py`** -- the transport acceptance test. Run
   `listen` on one machine (note the SteamID it prints), then
   `connect <that id>` on the other. A passing run prints
   `PASS: 20/20 reliable round-trips, in order`.

Each script carries a long docstring at the top with its exact
prerequisites, account/machine requirements, what you'll see, and its exit
criteria -- read it before running.
