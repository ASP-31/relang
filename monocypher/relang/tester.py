#!/usr/bin/env python3

import os
import sys
import json
import subprocess
import tempfile
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "project_config.json")) as f:
    CONFIG = json.load(f)

INPUT_TYPE = CONFIG["input_type"]



def run_one_tc(tc, program_cmd):
    timeout = tc.get("timeout", 30)
    try:
        r = subprocess.run(
            program_cmd,
            input=tc["data"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"id": tc["id"], "stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
    except subprocess.TimeoutExpired:
        return {"id": tc["id"], "stdout": "", "stderr": "TIMEOUT", "returncode": -1}
    except Exception as e:
        return {"id": tc["id"], "stdout": "", "stderr": str(e), "returncode": -1}

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <program_cmd>", file=sys.stderr)
        sys.exit(1)

    program_cmd = shlex.split(sys.argv[1])
    test_cases = json.load(sys.stdin)

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = [executor.submit(run_one_tc, tc, program_cmd) for tc in test_cases]
        results = [f.result() for f in as_completed(futures)]
    results.sort(key=lambda r: r["id"])
    json.dump(results, sys.stdout, indent=2)
if __name__ == "__main__":
    try:
        main()
    except Exception:
        json.dump([], sys.stdout)
