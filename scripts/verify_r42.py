"""Verify the R42 unbounded T5/T6 inductive report (v2 with in-flight writes)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="runs/R42/attempt1/t56_report.json")
    parser.add_argument("--out", default="runs/R42/attempt1/verification.json")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    checks = []

    def check(name, actual, expected):
        checks.append({"name": name, "ok": actual == expected,
                       "actual": actual, "expected": expected})

    check("schema", report.get("schema"), "r42_t56_unbounded_v2")
    check("z3_version", report.get("z3_version"), "5.3.1")

    t5 = report["t5"]
    check("t5.controllers", t5["controllers"], 2)
    check("t5.depth_bound", t5["depth_bound"], None)
    t5_expected = {
        "t5_no_a6": False,
        "t5_lease_naive": False,
        "t5_lease_closed": True,
        "t5_atomic_admit": True,
    }
    for name, safe in t5_expected.items():
        cfg = t5["configs"][name]
        check("t5.%s.safe" % name, cfg["safe"], safe)
        check("t5.%s.init" % name, cfg["init_satisfies_inv"], True)
        check("t5.%s.reachable" % name, cfg["reachable_committed"], 1)

    check("t5.no_a6.duplicate", t5["configs"]["t5_no_a6"]["duplicate_committed"], 2)
    check("t5.no_a6.trace", t5["configs"]["t5_no_a6"]["duplicate_witness"],
          ["query0", "query1", "issue0", "issue1", "commit0", "commit1"])
    naive = t5["configs"]["t5_lease_naive"]
    check("t5.lease_naive.duplicate", naive["duplicate_committed"], 2)
    check("t5.lease_naive.crash", "crash0" in naive["duplicate_witness"], True)
    closed = t5["configs"]["t5_lease_closed"]
    check("t5.lease_closed.blocked", closed["blocked_at"], "acquire1")
    check("t5.lease_closed.no_duplicate", closed["duplicate_committed"], 0)
    atomic = t5["configs"]["t5_atomic_admit"]
    check("t5.atomic_admit.blocked", atomic["blocked_at"], "commit1")
    check("t5.atomic_admit.no_duplicate", atomic["duplicate_committed"], 1)

    t6 = report["t6"]
    check("t6.depth_bound", t6["depth_bound"], None)
    check("t6.fence_unbounded", "unbounded" in t6["fence_domain"], True)
    t6_expected = {
        "t6_both": True,
        "t6_fence_only": False,
        "t6_finalize_only": False,
        "t6_neither": False,
    }
    for name, safe in t6_expected.items():
        cfg = t6["configs"][name]
        check("t6.%s.safe" % name, cfg["safe"], safe)
        check("t6.%s.init" % name, cfg["init_satisfies_inv"], True)
        if not safe:
            check("t6.%s.duplicate" % name, cfg["witness_committed"], 2)
            check("t6.%s.trace_nonempty" % name, len(cfg["witness"]) > 0, True)

    both = t6["configs"]["t6_both"]
    check("t6.both.reviewer_blocked", both["reviewer_blocked_at"], "not_original")
    check("t6.both.reviewer_committed", both["reviewer_committed"], 1)
    check("t6.recovery_direct_commit", both["recovery_direct_commit"],
          "rejected:not_original")

    passed = sum(1 for c in checks if c["ok"])
    body = {
        "status": "pass" if passed == len(checks) else "fail",
        "checks_total": len(checks),
        "checks_passed": passed,
        "failed": [c for c in checks if not c["ok"]],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: body[k] for k in ("status", "checks_total", "checks_passed")}))
    return 0 if body["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
