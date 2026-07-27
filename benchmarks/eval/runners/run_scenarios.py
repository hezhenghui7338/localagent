"""Run YAML scenarios against LA CLI / in-process helpers."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.eval.load_scenarios import load_scenarios
from benchmarks.eval.runners.judge import score_response
from benchmarks.locomo.runtime import configure_data_dir

_THRESHOLDS_FILE = _REPO_ROOT / "benchmarks" / "eval" / "thresholds.yaml"


def _default_env(data_dir: Path) -> dict[str, str]:
    return {
        "LA_DATA_DIR": str(data_dir),
        "LA_MEMORY_BACKEND": "json",
        "LA_MEM0_EMBEDDER_PROVIDER": "hash",
        "LA_INGEST_USE_LLM": "0",
        "LA_MEMORY_APPROVAL_AUTO": "1",
        "LA_MEMORY_APPROVAL_REQUIRED": "0",
        "LA_NEO4J": "0",
        "LA_MEMORY_GRAPH": "0",
        "LA_MEMORY_RERANK": "0",
        "LA_SKIP_OLLAMA_SETUP": "1",
        "LA_PROFILE_PIN_LLM": "0",
        "LA_LANG": "zh",
        "LA_EVAL_SKIP_JUDGE": os.environ.get("LA_EVAL_SKIP_JUDGE", "1"),
    }


def _run_la(args: list[str], *, env: dict[str, str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    base = os.environ.copy()
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "CURSOR_API_KEY", "TAVILY_API_KEY"):
        base.pop(key, None)
    base.update(env)
    return subprocess.run(
        [sys.executable, "-m", "localagent.cli", *args],
        input=input_text,
        text=True,
        capture_output=True,
        env=base,
        cwd=_REPO_ROOT,
        timeout=120,
    )


def _apply_setup(commands: list[list[str]], *, env: dict[str, str]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for cmd in commands:
        proc = _run_la(cmd, env=env)
        trace.append(
            {
                "cmd": cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-1000:],
            }
        )
        if proc.returncode != 0:
            raise RuntimeError(f"setup failed: {cmd} rc={proc.returncode}")
    return trace


def _eval_hard(assertion: dict[str, Any], *, text: str, trace: list[dict[str, Any]]) -> tuple[bool, str]:
    atype = assertion.get("type")
    if atype == "contains_any":
        values = assertion.get("values") or []
        if any(v in text for v in values):
            return True, "contains_any ok"
        return False, f"missing any of {values}"
    if atype == "not_contains":
        values = assertion.get("values") or []
        for v in values:
            if v in text:
                return False, f"forbidden substring present: {v}"
        return True, "not_contains ok"
    if atype == "returncode_zero":
        cmd = assertion.get("cmd") or []
        for step in trace:
            if step.get("cmd") == cmd:
                return step.get("returncode") == 0, f"returncode={step.get('returncode')}"
        return False, f"cmd not in trace: {cmd}"
    if atype == "memory_search_hits":
        marker = str(assertion.get("marker") or "")
        proc = _run_la(["memory", "search", marker], env=assertion["_env"])
        ok = proc.returncode == 0 and marker in proc.stdout
        return ok, proc.stdout[:300]
    return False, f"unknown hard assertion: {atype}"


def run_scenario(scenario: dict[str, Any], *, data_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    if scenario.get("setup"):
        setup_cmds = scenario["setup"].get("commands") or []
        trace.extend(_apply_setup(setup_cmds, env=env))

    combined_text = ""
    for step in trace:
        combined_text += step.get("stdout", "") + step.get("stderr", "")

    # in-process checks
    if scenario.get("in_process"):
        spec = scenario["in_process"]
        if spec.get("type") == "memory_search":
            from localagent.memory.scoped_recall import scoped_recall

            configure_data_dir(data_dir)
            hits = scoped_recall(str(spec.get("query") or ""), max_results=5)
            combined_text += "\n".join(h.get("text", "") for h in hits)

    hard = scenario.get("assertions", {}).get("hard") or []
    hard_results: list[dict[str, Any]] = []
    for assertion in hard:
        if assertion.get("type") == "memory_search_hits":
            assertion = {**assertion, "_env": env}
        ok, detail = _eval_hard(assertion, text=combined_text, trace=trace)
        hard_results.append({"assertion": assertion, "pass": ok, "detail": detail})

    soft = scenario.get("assertions", {}).get("soft") or []
    soft_results: list[dict[str, Any]] = []
    for item in soft:
        judged = score_response(
            criterion=str(item.get("criterion") or ""),
            prompt=str(scenario.get("id") or ""),
            response=combined_text[:4000],
            trace={"setup": trace},
        )
        min_score = int(item.get("min_score") or 4)
        score = judged.get("score")
        passed = score is None or score >= min_score
        soft_results.append(
            {
                "criterion": item.get("criterion"),
                "min_score": min_score,
                "score": score,
                "pass": passed,
                "rationale": judged.get("rationale"),
            }
        )

    hard_pass = all(r["pass"] for r in hard_results) if hard_results else True
    soft_pass = all(r["pass"] for r in soft_results) if soft_results else True
    return {
        "id": scenario.get("id"),
        "file": scenario.get("_file"),
        "pass": hard_pass and soft_pass,
        "hard": hard_results,
        "soft": soft_results,
        "trace": trace,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run LocalAgent eval scenarios")
    parser.add_argument("command", nargs="?", default="run", choices=["run"])
    parser.add_argument("--tier", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None, help="Write JSON report")
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.tier)
    if not scenarios:
        print(f"[eval] no scenarios for tier={args.tier}")
        return 0

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="la-eval-") as tmp:
        data_dir = Path(tmp) / "data"
        env = _default_env(data_dir)
        configure_data_dir(data_dir)

        for scenario in scenarios:
            result = run_scenario(scenario, data_dir=data_dir, env=env)
            results.append(result)
            status = "PASS" if result["pass"] else "FAIL"
            print(f"[eval] {status} {result['id']}")

    payload = {"tier": args.tier, "results": results, "passed": sum(1 for r in results if r["pass"])}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report → {args.report}")

    failed = [r["id"] for r in results if not r["pass"]]
    if failed:
        print(f"[eval] failed: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
