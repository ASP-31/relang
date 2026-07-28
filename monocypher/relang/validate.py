#!/usr/bin/env python3

import os
import sys
import json
import glob
import hashlib
import subprocess
import tempfile
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "project_config.json")) as f:
    CONFIG = json.load(f)

INPUT_TYPE = CONFIG["input_type"]
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"



def run_one_test(fpath, program_cmd, output_dir):
    with open(fpath) as f:
        tc = json.load(f)
    test_id = tc["id"]
    expected_path = os.path.join(output_dir, os.path.basename(fpath))
    if not os.path.exists(expected_path):
        return (test_id, None)
    with open(expected_path) as f:
        expected = json.load(f)
    expected_hash = hashlib.sha256(expected["output"].encode("utf-8")).hexdigest()
    actual_stdout = run_tool(program_cmd, tc)
    actual_hash = hashlib.sha256(actual_stdout.encode("utf-8")).hexdigest()
    return (test_id, actual_hash == expected_hash)

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <program_cmd>")
        sys.exit(1)

    program_cmd = shlex.split(sys.argv[1])
    input_dir = os.path.join(HERE, "input")
    output_dir = os.path.join(HERE, "output")

    test_files = sorted(glob.glob(os.path.join(input_dir, "*.json")))
    if not test_files:
        print("No test files found in input/")
        sys.exit(1)


    passed = 0
    total = len(test_files)

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {executor.submit(run_one_test, fpath, program_cmd, output_dir): fpath for fpath in test_files}
        for future in as_completed(futures):
            test_id, ok = future.result()
            if ok is None:
                print(f"  [SKIP] {test_id} (no expected output)")
                continue
            if ok:
                passed += 1
                print(f"  [{GREEN}PASS{RESET}] {test_id}")
            else:
                print(f"  [{RED}FAIL{RESET}] {test_id}")

    pct = (passed / total * 100) if total else 0
    print(f"\n{passed}/{total} passed ({pct:.1f}%)")
    sys.exit(0 if passed == total else 1)



def run_tool(program_cmd, tc):
    timeout = tc.get("timeout", 30)
    if INPUT_TYPE == "stdin":
        r = subprocess.run(
            program_cmd,
            input=tc["data"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".input", delete=False) as tmp:
            tmp.write(tc["data"])
            tmp_path = tmp.name
        try:
            r = subprocess.run(
                [*program_cmd, tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.stdout
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    main()
