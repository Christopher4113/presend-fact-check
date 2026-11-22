"""python cli.py cases/acme_stale.json [--fix] [--runs 5] [--fresh]
python cli.py --all [--fix]     # run every case, print table + stale precision/recall
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

from presend_check import check
from presend_check.consistency import run_consistency
from presend_check.models import CheckResult, ProspectRecord

COLORS = {"PASS": "\033[32m", "REVIEW": "\033[33m", "BLOCK": "\033[31m",
          "supported": "\033[32m", "unverified": "\033[33m", "stale": "\033[31m"}
RESET = "\033[0m"


def paint(s: str) -> str:
    return f"{COLORS.get(s, '')}{s}{RESET}" if sys.stdout.isatty() else s


def load_case(path: str | Path) -> dict:
    case = json.loads(Path(path).read_text())
    case["prospect"] = ProspectRecord(**case["prospect"])
    return case


def _matches(exp: dict, text: str) -> bool:
    terms = exp["match"] if isinstance(exp["match"], list) else [exp["match"]]
    return any(t.lower() in text.lower() for t in terms)


def score_case(case: dict, r: CheckResult) -> dict:
    """Claim-level stale TP/FP/FN against the case's expected labels."""
    claim_by_id = {c.id: c for c in r.claims}
    exp_stale = [e for e in case["expected"] if e["verdict"] == "stale"]
    pred_stale = [claim_by_id[v.claim_id] for v in r.verdicts if v.verdict == "stale"]
    tp = sum(1 for c in pred_stale if any(_matches(e, f"{c.text} {c.value}") for e in exp_stale))
    fn = sum(1 for e in exp_stale if not any(_matches(e, f"{c.text} {c.value}") for c in pred_stale))
    return {"tp": tp, "fp": len(pred_stale) - tp, "fn": fn}


def print_result(case: dict, r: CheckResult) -> None:
    by_id = {c.id: c for c in r.claims}
    print(f"\n{case.get('name', '')}  {case['prospect'].company} ({case['prospect'].domain})")
    print(f"decision: {paint(r.decision)}  (expected {case.get('expected_decision', '?')})  "
          f"{r.latency_ms} ms  {len(r.pages_checked)} pages")
    for v in r.verdicts:
        c = by_id[v.claim_id]
        print(f"  [{paint(v.verdict)}] {c.kind:<9} \"{c.text}\"")
        if v.corrected_value:
            print(f"      -> {v.corrected_value}")
        if v.quote:
            print(f"      \"{v.quote}\"  {v.source_url}")
        print(f"      {v.reason}")
    if r.fixed_draft:
        print(f"\nfixed draft:\n{r.fixed_draft}")
        if r.fixed_check:
            print(f"re-check: {paint(r.fixed_check.decision)}")


def run_all(fix: bool, fresh: bool, resume: bool = False) -> None:
    out = Path("results")
    out.mkdir(exist_ok=True)
    done = {}
    if resume and (out / "latest.json").exists():  # free-tier daily caps: keep finished cases
        done = {r["case"]: r for r in json.loads((out / "latest.json").read_text())["rows"]}
    rows, tot = [], {"tp": 0, "fp": 0, "fn": 0}
    for path in sorted(Path("cases").glob("*.json")):
        case = load_case(path)
        if path.stem in done:
            rows.append(done[path.stem])
        else:
            r = check(case["prospect"], case["draft"], fix=fix, fresh=fresh)
            print_result(case, r)
            rows.append({"case": path.stem, "category": case["category"], "domain": case["prospect"].domain,
                     "expected": case["expected_decision"], "decision": r.decision,
                     "ok": r.decision == case["expected_decision"], "latency_ms": r.latency_ms,
                         "pages": len(r.pages_checked), **score_case(case, r),
                         "result": r.model_dump(mode="json")})
            (out / "latest.json").write_text(json.dumps({"summary": {}, "rows": rows}, indent=2))
        for k in tot:
            tot[k] += rows[-1][k]
    precision = tot["tp"] / (tot["tp"] + tot["fp"]) if tot["tp"] + tot["fp"] else 0.0
    recall = tot["tp"] / (tot["tp"] + tot["fn"]) if tot["tp"] + tot["fn"] else 0.0
    summary = {"decision_accuracy": f"{sum(r['ok'] for r in rows)}/{len(rows)}",
               "stale_precision": round(precision, 3), "stale_recall": round(recall, 3), **tot,
               "median_latency_ms": int(statistics.median(r["latency_ms"] for r in rows)),
               "median_pages": statistics.median(r["pages"] for r in rows)}

    lines = ["| case | category | domain | expected | decision | ok | latency | pages |",
             "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['case']} | {r['category']} | {r['domain']} | {r['expected']} | {r['decision']} | "
              f"{'yes' if r['ok'] else 'no'} | {r['latency_ms'] / 1000:.1f}s | {r['pages']} |" for r in rows]
    table = "\n".join(lines)
    print("\n" + table + "\n")
    print(json.dumps(summary, indent=2))
    (out / "latest.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    (out / "latest.md").write_text(table + "\n\n```json\n" + json.dumps(summary, indent=2) + "\n```\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-send fact check for outreach drafts.")
    ap.add_argument("case", nargs="?", help="path to a case JSON")
    ap.add_argument("--all", action="store_true", help="run every case in cases/")
    ap.add_argument("--fix", action="store_true", help="rewrite stale facts, then re-verify")
    ap.add_argument("--runs", type=int, default=1, help="consistency check: run N times")
    ap.add_argument("--fresh", action="store_true", help="skip the page cache")
    ap.add_argument("--resume", action="store_true", help="with --all: reuse cases already in results/")
    a = ap.parse_args()

    if a.all:
        return run_all(a.fix, a.fresh, a.resume)
    if not a.case:
        ap.error("give a case path or --all")
    case = load_case(a.case)
    if a.runs > 1:
        report = run_consistency(case["prospect"], case["draft"], a.runs)
        for c in report["claims"]:
            flag = "  FLAKY" if c["flaky"] else ""
            print(f"{c['agreement']}  {c['majority']:<10} {c['claim']}{flag}  {c['verdicts']}")
        print(f"decision {report['decision_agreement']}: {report['decisions']}")
        return
    r = check(case["prospect"], case["draft"], fix=a.fix, fresh=a.fresh)
    print_result(case, r)
    print(json.dumps(score_case(case, r)))


if __name__ == "__main__":
    main()
