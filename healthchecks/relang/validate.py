#!/usr/bin/env python3
"""
Healthchecks HTTP Replay Test Runner

Reads input/*.json test cases, replays them against a running server,
normalizes dynamic values, hashes the output, and compares against
the hash of the expected output from output/*.json.

Usage:
    python validate.py http://localhost:8000
    python validate.py http://localhost:8000 --debug
"""

import sys
import json
import os
import re
import glob
import hashlib
import urllib.request
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(HERE, "input")
OUTPUT_DIR = os.path.join(HERE, "output")

CSRF_RE = re.compile(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\'][^"\']*["\']', re.I)
NONCE_RE = re.compile(r'nonce=["\'][^"\']*["\']', re.I)
TIMESTAMP_RE = re.compile(r"\b\d{10}\b")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
URL_RE = re.compile(r"https?://[^\"'\s<]+", re.I)
TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}\b")
ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+")
SITE_URL_RE = re.compile(r"https?://[^\"'\s<]+", re.I)
CHECKED_RE = re.compile(r"\s+checked\s*", re.I)
VALUE_RE = re.compile(r'\s+value="[^"]*"', re.I)
SELECTED_RE = re.compile(r"\s+selected\s*", re.I)
REPORT_DATE_RE = re.compile(r"<br\s*/?>\s*Next daily report date is[^<]*", re.I)


def normalize_json(obj, base_url, ref_url):
    if isinstance(obj, dict):
        return {k: normalize_json(v, base_url, ref_url) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_json(v, base_url, ref_url) for v in obj]
    if isinstance(obj, str):
        s = obj
        if base_url != ref_url:
            u = re.escape(base_url.rstrip("/"))
            s = re.sub(u, ref_url.rstrip("/"), s)
        if UUID_RE.search(s):
            return UUID_RE.sub("<UUID>", s)
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s):
            return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\.\d+", "<ISO_TS>", s)
        if TOKEN_RE.search(s):
            return TOKEN_RE.sub("<TOKEN>", s)
        if URL_RE.search(s):
            return URL_RE.sub("<URL>", s)
        return s
    return obj


def normalize_body(body, content_type, base_url, ref_url):
    ct = (content_type or "").lower()
    if "json" in ct:
        try:
            parsed = json.loads(body)
            return json.dumps(normalize_json(parsed, base_url, ref_url), sort_keys=True)
        except (json.JSONDecodeError, ValueError):
            pass
        return None
    if "html" in ct or "svg" in ct:
        return None
    if "text" in ct:
        s = URL_RE.sub("<URL>", body)
        s = UUID_RE.sub("<UUID>", s)
        s = TOKEN_RE.sub("<TOKEN>", s)
        return s
    return None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def reset_server_state(base_url):
    try:
        req = urllib.request.Request(f"{base_url}/__test/reset/")
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception:
        pass


def resolve_templates(template, state):
    def replacer(m):
        key = m.group(1)
        if key not in state:
            raise ValueError(f"Template key '{key}' not found")
        return str(state[key])
    return re.sub(r"\{(\w+)\}", replacer, template)


def extract_set_cookie(headers):
    cookies = {}
    raw = []
    if hasattr(headers, "get_all"):
        raw = headers.get_all("Set-Cookie") or []
    if not raw:
        v = headers.get("Set-Cookie") if hasattr(headers, "get") else None
        if v:
            raw = [v]
    for entry in raw:
        parts = entry.split(";")[0]
        if "=" in parts:
            k, v = parts.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def resolve_json_path(obj, path):
    parts = re.sub(r"^\$\.?", "", path).split(".")
    current = obj
    for part in parts:
        if current is None or not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def get_expected_output(test_id):
    exp_path = os.path.join(OUTPUT_DIR, f"{test_id}.json")
    if not os.path.exists(exp_path):
        return None
    with open(exp_path) as f:
        data = json.load(f)
    return data.get("output", "")


def run_test(fpath, base_url, ref_url):
    with open(fpath) as f:
        tc = json.load(f)

    test_id = tc["id"]
    steps = tc["data"]["steps"]
    state = {}
    cookies = {}
    out_steps = []

    reset_server_state(base_url)

    opener = urllib.request.build_opener(_NoRedirectHandler())

    for step_idx, step_data in enumerate(steps):
        req_def = step_data["request"]
        store_cookies_map = step_data.get("storeCookies", {})
        store_map = step_data.get("store", {})

        method = req_def.get("method", "GET")
        path = req_def.get("path", "/")

        try:
            resolved_path = resolve_templates(path, state)
        except ValueError:
            out_steps.append({"step": step_idx + 1, "status": 0, "content-type": ""})
            continue

        url = urllib.parse.urljoin(base_url, resolved_path)

        headers = {}
        for k, v in req_def.get("headers", {}).items():
            try:
                headers[k] = resolve_templates(v, state)
            except ValueError:
                pass

        if cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

        raw_body = req_def.get("body")
        body_data = None
        if raw_body is not None:
            try:
                if isinstance(raw_body, dict):
                    resolved_body = json.dumps(raw_body)
                else:
                    resolved_body = resolve_templates(raw_body, state)
            except ValueError:
                out_steps.append({"step": step_idx + 1, "status": 0, "content-type": ""})
                continue
            body_data = resolved_body.encode("utf-8")

        status = 0
        resp_headers = {}
        resp_body = ""

        try:
            request_obj = urllib.request.Request(url, data=body_data, headers=headers, method=method)
            with opener.open(request_obj, timeout=300) as resp:
                status = resp.status
                resp_headers = resp.headers
                resp_body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            status = e.code
            resp_headers = e.headers
            resp_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            out_steps.append({"step": step_idx + 1, "status": 0, "content-type": ""})
            continue

        new_cookies = extract_set_cookie(resp_headers)
        cookies.update(new_cookies)
        for state_key, cookie_name in store_cookies_map.items():
            if cookie_name in cookies:
                state[state_key] = cookies[cookie_name]

        if store_map:
            try:
                resp_obj = json.loads(resp_body)
            except (json.JSONDecodeError, ValueError):
                resp_obj = None
            if resp_obj is not None:
                for state_key, json_path in store_map.items():
                    value = resolve_json_path(resp_obj, json_path)
                    if value is not None:
                        state[state_key] = value

        store_html_map = step_data.get("storeHtml", {})
        for state_key, pattern in store_html_map.items():
            m = re.search(pattern, resp_body)
            if m and m.lastindex and m.group(1):
                state[state_key] = m.group(1)

        ct_raw = resp_headers.get("content-type", "") if hasattr(resp_headers, "get") else ""
        ct = ct_raw.split(";")[0].strip() or ""

        normalized = normalize_body(resp_body, ct, base_url, ref_url)
        step_out = {"step": step_idx + 1, "status": status, "content-type": ct}
        if normalized is not None:
            step_out["body"] = normalized
        out_steps.append(step_out)

    output_str = json.dumps(out_steps, sort_keys=True)
    return hashlib.sha256(output_str.encode("utf-8")).hexdigest(), out_steps


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate.py <server_url> [--debug]")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    ref_url = "http://localhost:8011"
    debug = "--debug" in sys.argv

    test_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.json")))
    if not test_files:
        print(f"No test files found in {INPUT_DIR}")
        sys.exit(1)

    passed = 0
    failed = 0

    for fpath in test_files:
        test_id = os.path.splitext(os.path.basename(fpath))[0]

        expected_output = get_expected_output(test_id)
        if expected_output is None:
            print(f"  [SKIP] {test_id} (no expected output)")
            continue

        expected_hash = hashlib.sha256(expected_output.encode("utf-8")).hexdigest()

        try:
            actual_hash, out_steps = run_test(fpath, base_url, ref_url)
        except Exception as e:
            print(f"  [FAIL] {test_id} (error: {e})")
            failed += 1
            continue

        if actual_hash == expected_hash:
            print(f"  [PASS] {test_id}")
            passed += 1
        else:
            print(f"  [FAIL] {test_id}")
            if debug:
                print(f"    actual hash:   {actual_hash}")
                print(f"    expected hash: {expected_hash}")
                for i, step in enumerate(out_steps):
                    exp_steps = json.loads(expected_output) if expected_output else []
                    e = exp_steps[i] if i < len(exp_steps) else {}
                    if step.get("status") != e.get("status"):
                        print(f"    step {i+1}: status expected={e.get('status')} actual={step.get('status')}")
                    if step.get("content-type") != e.get("content-type"):
                        print(f"    step {i+1}: ct expected={e.get('content-type')!r} actual={step.get('content-type')!r}")
                    eb = e.get("body", "")
                    ab = step.get("body", "")
                    if eb != ab:
                        print(f"    step {i+1}: body differs (expected len={len(eb)}, actual len={len(ab)})")
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed ({passed / total * 100:.1f}%) [{failed} failed]")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
