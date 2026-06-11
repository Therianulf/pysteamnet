---
name: project-shelved-state
description: pysteamnet shelved 2026-06-10 with M0-M3 complete and live-verified; what remains when Ben picks it back up
metadata:
  type: project
---

Ben shelved pysteamnet on 2026-06-10 ("until it's time to use it" — i.e.
when Bjorn's World reaches its Steam tier / M4). State at shelving:

- M0–M3 fully implemented, adversarially reviewed, 475 tests green
  (339 pure / 128 sdk-marked / 3 steam-marked live + 5 wrapper tests).
- Everything was still **uncommitted** at shelving time (Ben handles all
  git; no commits existed yet). If a fresh session finds no commits or
  missing files, that's why.
- Remaining work, all Ben-gated: (1) two-machine acceptance —
  lobby_host/lobby_join across machines, then `messages_pingpong.py
  listen` / `connect <id>` (PASS line = green light for the game's
  transport adapter); (2) license choice (pyproject says TBD);
  (3) first commit.
- Dev env facts: SDK v1.64 at ~/Downloads/sdk; run tests/examples with
  `PYSTEAMNET_LIBSTEAM_API=~/Downloads/sdk/redistributable_bin/osx` and
  a `steam_appid.txt` containing 480 (gitignored — recreate after clone).
- Naming settled 2026-06-10: everything is `pysteamnet` (one lowercase
  word — never `py_steam_net`, which collides with an unrelated Rust
  project on PyPI normalization). Ben said he'd rename the repo folder
  from `pySteamNet` to `pysteamnet`; after that the editable install
  needs a re-run (`pip install -e .`).
- Project memory lives IN THE REPO at `.claude/memory/` (this file);
  the `~/.claude/projects/<slug>/memory/MEMORY.md` is just a redirect
  pointer. After the repo rename, recreate that pointer under the new
  slug `-Users-blarson-Github-pysteamnet` if it's missing.
- All pinned technical facts live in the repo's CLAUDE.md ("Pinned SDK &
  resolved symbols" block) — read that first, not this. See
  [[zero-dep-law-runtime-only]] for the dev-tooling stance.
