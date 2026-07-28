#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

TEAM_TOKEN = "3b6cb2e2d18ae6c89c99bc24c0c6e3be684d2e60c9882cf43cd0b68bb85348de"
API_BASE = "http://85.211.196.199:8080"
BATCH_SIZE = 100


def api_post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Team-Token": TEAM_TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_get(url):
    req = urllib.request.Request(url, headers={"X-Team-Token": TEAM_TOKEN}, method="GET")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    if not TEAM_TOKEN:
        print("Error: RELANG_TOKEN env var not set", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <tool_command>", file=sys.stderr)
        sys.exit(1)

    tool_cmd = sys.argv[1]

    if "source" in tool_cmd:
        print("⚠️  **Do NOT submit the source reference implementation.**")
        print("> Only implement and submit your code from `target/`.")
        print("> Submitting `source/` may result in **disqualification**.")
        confirm = input("Are you sure you want to continue? (yes/no): ")
        if confirm.strip().lower() != "yes":
            print("Submission aborted.", file=sys.stderr)
            sys.exit(1)

    config_path = os.path.join("relang", "project_config.json")
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    project_id = config["project_id"]

    print(f"Creating session for project {project_id}...")
    session = api_post(API_BASE + "/api/session/create",
                       {"projectId": project_id, "teamToken": TEAM_TOKEN})
    session_token = session["sessionToken"]
    total_tests = session["totalTests"]
    batch_size = session.get("batchSize", BATCH_SIZE)
    print(f"Session created: {total_tests} tests total")

    tester_py = os.path.join("relang", "tester.py")
    if not os.path.exists(tester_py):
        print(f"Error: {tester_py} not found", file=sys.stderr)
        sys.exit(1)

    all_hashes = {}
    all_empty = []
    batch_num = 0
    done = False

    while not done:
        batch_num += 1
        print(f"\n--- Batch {batch_num} ---")

        batch = api_get(
            f"{API_BASE}/api/inputs/next-batch?session={session_token}&size={batch_size}"
        )

        if batch.get("done"):
            done = True
            break

        test_cases = batch["testCases"]

        result = subprocess.run(
            [sys.executable, tester_py, tool_cmd],
            input=json.dumps(test_cases),
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            print(f"  tester.py exit code {result.returncode}", file=sys.stderr)

        try:
            results = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"  Failed to parse tester.py output: {e}", file=sys.stderr)
            sys.exit(1)

        file_hashes = {}
        empty_tests = []
        for r in results:
            stdout = r.get("stdout", "")
            if not stdout.strip():
                empty_tests.append(r["id"])
            h = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
            file_hashes[r["id"]] = h

        all_hashes.update(file_hashes)
        all_empty.extend(empty_tests)

        submit_resp = api_post(API_BASE + "/api/submit-hash", {
            "projectId": project_id,
            "fileHashes": file_hashes,
            "excludedTestIds": empty_tests,
        })

        passed = submit_resp["passedTestCases"]
        total = submit_resp["totalTestCases"]
        excluded = submit_resp.get("excludedTestCases", 0)
        pct = (passed / total * 100) if total else 0
        score = submit_resp.get("finalScore", 0)
        failed_ids = submit_resp.get("failedTestIds", [])
        real_empty_failed = [t for t in empty_tests if t in failed_ids]
        print(f"  Batch: {passed}/{total} passed | Running: {pct:.1f}%")
        if real_empty_failed:
            print(f"  ⚠ {len(real_empty_failed)} test(s) produced empty output — your tool may not be finding the input files", file=sys.stderr)

        done = batch.get("done", False)

    total_all = len(all_hashes)
    final_pct = 0
    final_score = 0

    if total_all > 0:
        try:
            final = api_post(API_BASE + "/api/submit-hash", {
                "projectId": project_id,
                "fileHashes": all_hashes,
                "isFinal": True,
                "excludedTestIds": all_empty,
            })
            final_pct = final.get("passedTestCases", 0) / max(final.get("totalTestCases", 1), 1) * 100
            final_score = final.get("finalScore", 0)
        except Exception as e:
            print(f"  Final submission error: {e}", file=sys.stderr)

    print(f"\n{'='*45}")
    print(f"  FINAL: {total_all} tests")
    print(f"  SCORE: {final_score:.1f} points")
    print(f"  PASS:  {final_pct:.1f}%")
    print(f"{'='*45}")


if __name__ == "__main__":
    main()
