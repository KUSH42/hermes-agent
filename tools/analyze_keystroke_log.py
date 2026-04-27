#!/usr/bin/env python3
"""Analyze ~/.hermes/keystroke.jsonl for convergence-plan Step 6a.

Usage:
    python tools/analyze_keystroke_log.py [path]

Reports:
  1. Per-key total count + per-(phase, kind, density) breakdown
  2. Zero-press keys from the BINDINGS allowlist
  3. `t` press rate: kind=null vs kind=non-null (classifier disagreement proxy)
  4. Density distribution at first-key time per block
  5. Mouse click heatmap: per-widget-type click counts + scroll vs click ratio
  6. Component interaction totals: per-action counts + density_toggle from→to matrix
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Keys known to be bound — every key present in ToolPanel.BINDINGS.
# Does NOT include navigation-only or unbound keys (escape, tab, space, up/down/etc).
_BOUND_KEYS = frozenset({
    "t", "T", "y", "Y", "C", "H", "I", "u", "o", "e", "p", "P",
    "r", "a", "E", "O", "f", "j", "k", "J", "K", "D", "x",
    "plus", "minus", "asterisk", "less_than_sign", "greater_than_sign",
    "question_mark", "enter", "f1", "shift+d",
})


def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def report(rows: list[dict]) -> None:
    total_by_key: Counter[str] = Counter()
    breakdown: dict[str, Counter] = defaultdict(Counter)
    first_density_per_block: dict[str, str] = {}
    t_by_kind_null: Counter[str] = Counter()   # "null" vs "non-null"

    click_by_widget: Counter[str] = Counter()
    scroll_total: int = 0
    click_total: int = 0

    component_by_action: Counter[str] = Counter()
    density_toggle_matrix: Counter[tuple[str, str]] = Counter()

    for row in rows:
        etype = row.get("event_type", "key")  # back-compat: old rows lack event_type

        if etype == "key":
            key = row["key"]
            ctx = (row["phase"], row.get("kind"), row["density"])
            total_by_key[key] += 1
            breakdown[key][ctx] += 1
            block_id = row["block_id"]
            if block_id not in first_density_per_block:
                first_density_per_block[block_id] = row["density"]
            if key == "t":
                bucket = "kind=null" if row.get("kind") is None else "kind=non-null"
                t_by_kind_null[bucket] += 1

        elif etype == "mouse":
            button = row.get("button", "unknown")
            widget = row.get("widget", "unknown")
            if button in ("scroll_up", "scroll_down"):
                scroll_total += 1
            else:
                click_total += 1
                click_by_widget[widget] += 1

        elif etype == "component":
            action = row.get("action", "unknown")
            component_by_action[action] += 1
            if action == "density_toggle":
                extra = row.get("extra") or {}
                key_from = extra.get("from", "?")
                key_to = extra.get("to", "?")
                density_toggle_matrix[(key_from, key_to)] += 1

    print("=== 1. Per-key totals ===")
    for key, count in total_by_key.most_common():
        print(f"  {key:30s}  {count:6d}")
        for ctx, n in breakdown[key].most_common(5):
            print(f"    {str(ctx):60s}  {n}")

    print("\n=== 2. Zero-press bound keys ===")
    zero = sorted(_BOUND_KEYS - set(total_by_key))
    print("  " + ", ".join(zero) if zero else "  (none)")

    print("\n=== 3. `t` key — classifier disagreement proxy ===")
    for bucket, n in t_by_kind_null.items():
        print(f"  {bucket}: {n}")
    total_t = sum(t_by_kind_null.values())
    if total_t:
        non_null = t_by_kind_null.get("kind=non-null", 0)
        print(f"  rate at kind!=null: {non_null/total_t:.1%}")

    print("\n=== 4. Density at first keypress per block ===")
    density_dist: Counter[str] = Counter(first_density_per_block.values())
    for tier, n in density_dist.most_common():
        print(f"  {tier:10s}  {n:6d}")

    print("\n=== 5. Mouse — click heatmap + scroll ratio ===")
    print(f"  total clicks:  {click_total}")
    print(f"  total scrolls: {scroll_total}")
    if click_total + scroll_total:
        ratio = scroll_total / (click_total + scroll_total)
        print(f"  scroll ratio:  {ratio:.1%}")
    print("  clicks by widget type:")
    for widget, n in click_by_widget.most_common():
        print(f"    {widget:40s}  {n:6d}")

    print("\n=== 6. Component interactions ===")
    for action, n in component_by_action.most_common():
        print(f"  {action:30s}  {n:6d}")
    if density_toggle_matrix:
        print("  density_toggle from→to matrix:")
        for (frm, to), n in density_toggle_matrix.most_common():
            print(f"    {frm:12s} → {to:12s}  {n}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".hermes" / "keystroke.jsonl"
    if not path.exists():
        print(f"No log at {path}", file=sys.stderr)
        sys.exit(1)
    report(load(path))
