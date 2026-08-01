# 🧩 ARC-AGI Solved Tasks — Unified, Verified Catalog

This repo is the single, unified home for TranscendPlexity's ARC-AGI static-grid puzzle
solvers. It merges what used to be three separate repos
(this repo, formerly named `SOLVED-540-of-540`, plus `SOLVED---abc82100` and
`13-Impossible-ARC-Tasks-SOLVED`) — the other two are now archived and point here.

## The real, verified number

**514 independently-verified solvers**, out of 632 total solver files in this repo.
Verified means: real task data exists (either bundled here or in the official public
ARC-AGI-1 / ARC-AGI-2 datasets), and running `solve(grid)` produces an **exact match**
against the held-out test pair(s) — not partial/cell-overlap credit.

| Source dataset | Verified solved |
|---|---|
| ARC-AGI-1 (evaluation set) | 18 |
| ARC-AGI-2 (evaluation set) | 120 |
| ARC-AGI-2 (training set) | 376 |
| **Total verified** | **514** |
| Claimed "solved" in `catalog.json` but **no task data exists anywhere** (not in this repo, not in the official `fchollet/ARC-AGI` or `arcprize/ARC-AGI-2` datasets) — cannot be verified | 118 |
| **Total solver files in repo** | **632** |

Reproduce this yourself:

```bash
python3 verify_all.py
# => Results: 514 passed, 0 failed, 118 skipped (skipped = no task data to check against)
```

`catalog.json` reflects this exactly — every entry has a `status` of either
`verified_solved` (with a `verification` note) or `unverified_claim`. Nothing is silently
marked "✅ Solved / 100%" without backing data anymore.

### Important caveats for honest interpretation

- **Most of the verified count (376/514) is against the ARC-AGI-2 *training* set**, not the
  harder held-out evaluation set. Training-set tasks are meant to be learnable/inspectable,
  so this is a real result but a lower bar than evaluation-set generalization. Only
  **138** (18 + 120) verified solves are against the two official held-out evaluation sets.
- **118 solver files reference task IDs with no discoverable source data.** These were
  previously all marked "✅ Solved (100%)" in `catalog.json` — that was false confidence
  with nothing to check it against. One of them (`0ae0773b`) even describes itself
  internally as "Memorize degenerate training pairs," i.e. it was written to fit specific
  training examples rather than induce a general rule — the opposite of what ARC is
  supposed to test.
- **`arc3/` is a separate, different system** — an interactive game-playing agent for
  ARC-AGI-3 (not a static grid solver). It is **not** included in the 514 count above.
  This exact agent was independently tested and scored **2/183** on real ARC-AGI-3 levels —
  far below the "20/20 (100%)" figure quoted for it elsewhere in this account's history.
- **`re-arc/` is also separate** — a bundled claim of "125/125 (100%)" on the RE-ARC
  procedural-abstraction benchmark. Its `solves/` directory actually contains 601 entries,
  not 125, and this claim has **not** been independently re-verified here. Treat it as
  unverified pending further audit.
- Previous headline claims across this account's repos have been mutually inconsistent:
  "540/540 (100%)", "514 standalone solvers", "422 solvers", and "665/665 combined" have
  all been used to describe overlapping-but-different subsets of this same body of work.
  This README replaces all of those with the one number that's actually been
  independently reproduced end-to-end: **514**.

## How It Works

Each solver is a pure Python function that takes a 2D grid (list of lists of ints) and
returns the transformed output grid. No ML models, no LLMs at inference time — just code,
synthesized offline using Claude Opus 4.6 via iterative program generation (observe
training examples → hypothesize rule → write `solve(grid)` → test → iterate → verify
against held-out test pairs).

```python
# Example: solves/0934a4d8/solver.py
def solve(grid: list[list[int]]) -> list[list[int]]:
    # Deterministic transformation logic
    ...
```

## Repository Structure

```
solves/{task_id}/solver.py   # 632 solver directories (514 verified, 118 unverifiable)
dataset/tasks/{task_id}.json # Bundled task data for verifiable tasks
catalog.json                 # Per-task metadata incl. honest status field
verify_all.py                # Run this to reproduce the 514/632 result yourself
arc3/                        # SEPARATE interactive-game agent (not part of the 514)
re-arc/                      # SEPARATE, unverified RE-ARC benchmark claim
kaggle_2025/                 # Official Kaggle ARC Prize 2025 competition data
viz/                         # Per-task HTML grid visualizations
```

## Running a Solver

```bash
python3 -c "
import json, importlib.util

task_id = '0934a4d8'
with open(f'dataset/tasks/{task_id}.json') as f:
    task = json.load(f)

spec = importlib.util.spec_from_file_location('solver', f'solves/{task_id}/solver.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

for pair in task['test']:
    result = mod.solve(pair['input'])
    assert result == pair['output'], 'Mismatch!'
    print(f'{task_id}: PASS')
"
```

## Verification protocol

1. Agent writes `solver.py` based on training examples only.
2. Solver is tested against all training pairs.
3. Solver is independently verified against test pairs (never seen during development).
4. Only solvers with backing task data can be verified at all — see caveats above for the
   118 that currently cannot be.

## Contact

Evan Pieser — epieser@protonmail.com
