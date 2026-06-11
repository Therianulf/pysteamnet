---
name: zero-dep-law-runtime-only
description: The zero-dependency law applies to the runtime/user side only — dev tooling is unrestricted (Ben, 2026-06-10)
metadata:
  type: feedback
---

Ben clarified during M0–M3 planning (2026-06-10): "the zero dependency mindset is more for the user side, not the dev. we can use all the tooling we want."

**Why:** CLAUDE.md's "zero runtime dependencies — ctypes and the standard library, period" protects consumers of the package (nothing to build, nothing to install). It was never meant to forbid developer tooling.

**How to apply:** `[project] dependencies` stays `[]` forever, but dev-only tools (pytest in `optional-dependencies.dev`, linters, type checkers, codegen scripts over steam_api.json) are fine without asking. Don't re-ask permission for dev tooling; do keep the runtime surface pure stdlib.
