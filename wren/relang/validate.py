#!/usr/bin/env python3

import os
import sys
import json
import hashlib
import subprocess
import tempfile
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "project_config.json")) as f:
    CONFIG = json.load(f)

INPUT_TYPE = CONFIG["input_type"]
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"



def run_one_test(fpath, program_cmd, input_dir, output_dir):
    with open(fpath) as f:
        tc = json.load(f)
    test_id = tc["id"]
    rel = os.path.relpath(fpath, input_dir)
    expected_path = os.path.join(output_dir, rel)
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

    test_files = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f.endswith(".json"):
                test_files.append(os.path.join(root, f))
    test_files.sort()

    if not test_files:
        print("No test files found in input/")
        sys.exit(1)


    passed = 0
    total = len(test_files)

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {executor.submit(run_one_test, fpath, program_cmd, input_dir, output_dir): fpath for fpath in test_files}
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
    stdin_data = _extract_stdin(tc["data"])

    if INPUT_TYPE == "stdin":
        r = subprocess.run(
            program_cmd,
            input=tc["data"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout

    wd = tempfile.mkdtemp(prefix="wren_test_")

    try:
        test_rel = os.path.join("test", tc["id"] + ".wren")
        test_path = os.path.join(wd, test_rel)
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        with open(test_path, "w") as f:
            f.write(tc["data"])

        for rel_path, content in (tc.get("files") or {}).items():
            fpath = os.path.join(wd, "test", rel_path)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w") as f:
                f.write(content)

        r = subprocess.run(
            [*program_cmd, test_rel],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=wd,
        )
        return r.stdout
    finally:
        shutil.rmtree(wd, ignore_errors=True)


STDIN_PATTERN = None


def _extract_stdin(data):
    global STDIN_PATTERN
    if STDIN_PATTERN is None:
        import re
        STDIN_PATTERN = re.compile(r'// stdin: (.*)')
    stdin_lines = []
    for line in data.splitlines():
        m = STDIN_PATTERN.search(line)
        if m:
            stdin_lines.append(m.group(1))
    return "\n".join(stdin_lines) if stdin_lines else None


if __name__ == "__main__":
    main()
