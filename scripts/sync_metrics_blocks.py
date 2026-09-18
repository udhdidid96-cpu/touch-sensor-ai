#!/usr/bin/env python3
"""Render headline figures into the docs from Data/metrics.json.

Rule 1 of this repository is "never type a number into the paper by hand".
`--verify-metrics` enforces code-vs-metrics.json. Nothing enforced
docs-vs-metrics.json, and the gap bit twice:

  * v5.0: the whitepaper quoted 90.00% / macro F1 0.8791; the code produced
    87.50% / 0.8498, and nobody noticed for weeks.
  * 2026-09-17: docs/ACTION_PLAN.md headlined episode sensitivity 87.5% and
    6.0 alarms/hour as "the numbers that should go on stage". README.md had
    formally retracted that pair on 2026-08-19 -- it belongs to a RandomForest
    that was already replaced. The shipped model measures 100.0% and 7.8/hour,
    so the plan was under-reporting its own result by 12.5 points.

A document opts in by wrapping a region:

    <!-- metrics:episode_headline_th -->
    ... generated, do not edit by hand ...
    <!-- /metrics:episode_headline_th -->

    python scripts/sync_metrics_blocks.py            # rewrite every region
    python scripts/sync_metrics_blocks.py --check    # exit 1 if any is stale

The --check mode is what tests/test_doc_metrics_sync.py runs, so a stale
number fails the suite the same way a code change that moves a metric does.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Callable, Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS_PATH = os.path.join(REPO_ROOT, "Data", "metrics.json")

# Markdown trees to scan. Data/METRICS.md is excluded on purpose: --report
# writes it, and a second writer for one file is how they drift apart.
SCAN_DIRS = [REPO_ROOT, os.path.join(REPO_ROOT, "docs")]

BLOCK_RE = re.compile(
    r"(?P<open><!--\s*metrics:(?P<key>[a-z0-9_]+)\s*-->)"
    r"(?P<body>.*?)"
    r"(?P<close><!--\s*/metrics:(?P=key)\s*-->)",
    re.DOTALL,
)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _ci(pair: List[float]) -> str:
    return f"{pair[0] * 100:.1f}–{pair[1] * 100:.1f}"


def episode_headline_th(m: Dict[str, Any]) -> str:
    ep = m["episode_level"]
    op = ep["operating_point"]
    return (
        f"sensitivity **{_pct(ep['sensitivity'])}** (95% CI {_ci(ep['sensitivity_ci'])}) "
        f"· false alarm **{_pct(ep['false_alarm_rate'])} ต่อ recording** "
        f"(95% CI {_ci(ep['false_alarm_ci'])}) "
        f"= **{ep['alarms_per_hour']:.1f} ครั้ง/ชม**\n"
        f"· latency กลาง **{ep['median_latency_s']:.2f} วิ** "
        f"(แย่สุด {ep['max_latency_s']:.2f} วิ) "
        f"· พลาด {len(ep['missed'])} เหตุการณ์\n"
        f"· operating point {op['window']}-of-{op['votes']} hold {op['hold']} "
        f"· ที่มา `Data/metrics.json` ({m['generated']}, v{m['version']})"
    )


def episode_headline_en(m: Dict[str, Any]) -> str:
    ep = m["episode_level"]
    op = ep["operating_point"]
    return (
        f"Episode-level, out-of-fold, {op['window']}-of-{op['votes']} hold {op['hold']}: "
        f"sensitivity **{_pct(ep['sensitivity'])}** [{_ci(ep['sensitivity_ci'])}], "
        f"false alarm **{_pct(ep['false_alarm_rate'])}** per recording "
        f"[{_ci(ep['false_alarm_ci'])}] = **{ep['alarms_per_hour']:.1f} alarms/hour**, "
        f"median time-to-alarm **{ep['median_latency_s']:.2f} s** "
        f"(worst {ep['max_latency_s']:.2f} s), {len(ep['missed'])} missed events. "
        f"Source: `Data/metrics.json` ({m['generated']}, v{m['version']})."
    )


def file_level_en(m: Dict[str, Any]) -> str:
    rf = m["random_forest"]
    ds = m["dataset"]
    return (
        f"File-level ({rf['cv']} CV, {len(rf['seeds'])} seeds, "
        f"{ds['files']} files / {ds['frames']} frames / {ds['features']} features): "
        f"accuracy **{_pct(rf['accuracy_mean'])}**, macro F1 **{rf['macro_f1_mean']:.4f}**. "
        f"Source: `Data/metrics.json` ({m['generated']}, v{m['version']})."
    )


RENDERERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "episode_headline_th": episode_headline_th,
    "episode_headline_en": episode_headline_en,
    "file_level_en": file_level_en,
}


def markdown_files() -> List[str]:
    seen: List[str] = []
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if not os.path.isfile(path) or not name.lower().endswith(".md"):
                continue
            if os.path.abspath(path) == os.path.abspath(
                    os.path.join(REPO_ROOT, "Data", "METRICS.md")):
                continue
            if path not in seen:
                seen.append(path)
    return seen


def sync(check_only: bool = False) -> int:
    if not os.path.isfile(METRICS_PATH):
        print(f"metrics.json not found at {METRICS_PATH}")
        print("Generate it first:  python main.py --report")
        return 2
    with open(METRICS_PATH, "r", encoding="utf-8") as fh:
        metrics = json.load(fh)

    stale: List[str] = []
    unknown: List[str] = []
    written = 0
    blocks = 0

    for path in markdown_files():
        with open(path, "r", encoding="utf-8") as fh:
            original = fh.read()

        def replace(match: "re.Match[str]") -> str:
            nonlocal blocks
            blocks += 1
            key = match.group("key")
            render = RENDERERS.get(key)
            rel = os.path.relpath(path, REPO_ROOT)
            if render is None:
                unknown.append(f"{rel}: unknown block key 'metrics:{key}'")
                return match.group(0)
            body = "\n" + render(metrics).strip() + "\n"
            if body != match.group("body"):
                stale.append(rel + f" [metrics:{key}]")
            return match.group("open") + body + match.group("close")

        updated = BLOCK_RE.sub(replace, original)
        if updated != original and not check_only:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(updated)
            written += 1

    for line in unknown:
        print("ERROR " + line)
    if check_only:
        for line in stale:
            print("STALE " + line)
        if stale or unknown:
            print(f"\n{len(stale)} stale block(s), {len(unknown)} unknown key(s) "
                  f"out of {blocks} scanned.")
            print("Fix with:  python scripts/sync_metrics_blocks.py")
            return 1
        print(f"OK - {blocks} metrics block(s) match Data/metrics.json.")
        return 0

    print(f"{blocks} metrics block(s) scanned, {written} file(s) rewritten.")
    return 1 if unknown else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if any block is out of date")
    args = ap.parse_args()
    return sync(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
