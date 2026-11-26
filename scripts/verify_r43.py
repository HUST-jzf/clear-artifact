"""Verify the frozen R43 Atomix-original run against its summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASELINE_LEAKS = {
    "Tx-Full": 0,
    "TCC-Confirm": 0,
    "Mutex+WAL+Rollback": 0,
    "Saga-Compensation": 400,
    "Atomix-MisclassifiedIrreversible": 300,
    "Checkpoint-Replay": 200,
    "No-Tx": 500,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/R43/attempt1")
    parser.add_argument("--out", default="runs/R43/attempt1/verification.json")
    args = parser.parse_args()

    run = Path(args.run)
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    checks = []

    def check(name, actual, expected):
        checks.append({"name": name, "ok": actual == expected,
                       "actual": actual, "expected": expected})

    check("schema", result.get("schema"), "r43_atomix_original_v1")
    check("status", result.get("status"), "pass")
    check("commit", result["upstream"]["commit"],
          "61e411be662bb021634f0e84bc184bf6074905b4")
    check("tests.passed", result["tests"]["passed"], 187)
    check("tests.failed", result["tests"]["failed"], 2)
    check("tests.skipped", result["tests"]["skipped"], 1)

    b3 = result["b3_irreversible"]
    check("b3.invalid", b3["invalid_trials"], 3500)
    check("b3.valid", b3["valid_send_trials"], 3500)
    for name, leaks in BASELINE_LEAKS.items():
        check("b3.%s.leaks" % name, b3["per_baseline"][name]["leaks"], leaks)
        check("b3.%s.invalid" % name, b3["per_baseline"][name]["invalid"], 500)
        check("b3.%s.delivered" % name, b3["per_baseline"][name]["delivered"], 500)

    raw = json.loads((run / "atomix/atomix_b3.json").read_text(encoding="utf-8"))
    check("b3.raw.rows", len(raw["rows"]), 35)
    check("b3.raw.invalid", raw["denominators"]["invalid_pre_externalization_trials"], 3500)
    check("b3.raw.valid", raw["denominators"]["valid_send_trials"], 3500)

    e5b2 = result["e5_b2_frontier_contract"]
    check("e5b2.correct.out_of_order", e5b2["correct"]["out_of_order_commits"], 0)
    check("e5b2.correct.blocked", e5b2["correct"]["blocked_on_correct"], 0)
    check("e5b2.no_advance.blocked", e5b2["no-advancement"]["blocked_on_correct"], 400)
    check("e5b2.premature.out_of_order", e5b2["premature"]["out_of_order_commits"], 200)

    e5b3 = result["e5_b3_crash_window"]
    for p in ("P1", "P2", "P3", "P4"):
        check("e5b3.%s.trials" % p, e5b3[p]["trials"], 50)
        check("e5b3.%s.duplicates" % p, e5b3[p]["duplicates"], 0)
        check("e5b3.%s.lost" % p, e5b3[p]["lost_effects"], 0)
        check("e5b3.%s.blocked" % p, e5b3[p]["recovery_blocked"], 50 if p in ("P2", "P3") else 0)

    fp = json.loads((run / "atomix/b3_fp_sweep_real_sink.json").read_text(encoding="utf-8"))
    check("fp.cells", sorted(fp["cells"].keys()), ["0.02", "0.1", "0.3"])
    for cell in fp["cells"].values():
        check("fp.rows", len(cell["rows"]), 35)
        check("fp.invalid", cell["denominators"]["invalid_pre_externalization_trials"], 3500)
        check("fp.post_externalization", cell["denominators"]["post_externalization_logged"], 0)

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
