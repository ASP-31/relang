#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
REF_URL = "http://localhost:8011"

with open(os.path.join(HERE, "project_config.json")) as f:
    CONFIG = json.load(f)

CSRF_RE = re.compile(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\'][^"\']*["\']', re.I)
NONCE_RE = re.compile(r'nonce=["\'][^"\']*["\']', re.I)
TIMESTAMP_RE = re.compile(r"\b\d{10}\b")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
URL_RE = re.compile(r"https?://[^\"'\s<]+", re.I)
TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}\b")
ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+")
CHECK_COUNT_RE = re.compile(r"\d+\s+checks,\s*\d+\s+integrations", re.I)
SITE_URL_RE = re.compile(r"https?://[^\"'\s<]+", re.I)
CHECKED_RE = re.compile(r"\s+checked\s*", re.I)
VALUE_RE = re.compile(r'\s+value="[^"]*"', re.I)
SELECTED_RE = re.compile(r"\s+selected\s*", re.I)
REPORT_DATE_RE = re.compile(r"<br\s*/?>\s*Next daily report date is[^<]*", re.I)


def normalize_html(s):
    s = CSRF_RE.sub("", s)
    s = NONCE_RE.sub("", s)
    s = TIMESTAMP_RE.sub("", s)
    s = URL_RE.sub("<URL>", s)
    s = UUID_RE.sub("<UUID>", s)
    s = ISO_TS_RE.sub("<ISO_TS>", s)
    s = CHECK_COUNT_RE.sub("CHECKS_COUNT", s)
    s = TOKEN_RE.sub("<TOKEN>", s)
    s = CHECKED_RE.sub("", s)
    s = SELECTED_RE.sub("", s)
    s = VALUE_RE.sub("", s)
    s = REPORT_DATE_RE.sub("", s)
    s = re.sub(r"\s+>", ">", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r">\s+<", "><", s)
    return s.strip()


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


def resolve_template(s, state):
    def replacer(m):
        key = m.group(1)
        if key not in state:
            raise ValueError(f"Template key '{key}' not found")
        return str(state[key])
    return re.sub(r"\{(\w+)\}", replacer, s)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def reset_server(base_url):
    try:
        req = urllib.request.Request(f"{base_url}/__test/reset/")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <server_url>", file=sys.stderr)
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    ref_url = REF_URL
    test_cases = json.load(sys.stdin)

    results = []
    for tc in test_cases:
        data = tc.get("data", {})
        if isinstance(data, str):
            data = json.loads(data)
        steps = data.get("steps", [])
        tid = tc["id"]
        state = {}
        cookies = {}
        step_results = []

        reset_server(base_url)

        for step_idx, step in enumerate(steps):
            req_def = step.get("request", {})
            exp_def = step.get("expected", {})

            method = req_def.get("method", "GET")
            path = req_def.get("path", "/")

            try:
                resolved_path = resolve_template(path, state)
            except ValueError as e:
                step_results.append({"step": step_idx + 1, "error": str(e)})
                continue

            url = urljoin(base_url, resolved_path)

            headers = {}
            for k, v in req_def.get("headers", {}).items():
                try:
                    headers[k] = resolve_template(v, state)
                except ValueError:
                    headers[k] = v

            if cookies:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

            body_raw = req_def.get("body")
            body_data = None
            if body_raw is not None:
                try:
                    if isinstance(body_raw, dict):
                        resolved_body = json.dumps(body_raw)
                    else:
                        resolved_body = resolve_template(body_raw, state)
                except ValueError as e:
                    step_results.append({"step": step_idx + 1, "error": str(e)})
                    continue
                body_data = resolved_body.encode("utf-8")
                if "Content-Type" not in headers and "content-type" not in headers:
                    headers["Content-Type"] = "application/json"

            opener = urllib.request.build_opener(NoRedirect())
            status = 0
            resp_headers = {}
            resp_body = ""
            try:
                req = urllib.request.Request(url, data=body_data, headers=headers, method=method)
                with opener.open(req, timeout=300) as resp:
                    status = resp.status
                    resp_headers = resp.headers
                    resp_body = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                status = e.code
                resp_headers = e.headers
                resp_body = e.read().decode("utf-8", errors="replace")
            except Exception as e:
                step_results.append({"step": step_idx + 1, "error": str(e)})
                continue

            actual_ct = (resp_headers.get("Content-Type") or "").split(";")[0].strip() if hasattr(resp_headers, "get") else ""

            normalized = normalize_body(resp_body, actual_ct, base_url, ref_url)
            step_out = {
                "step": step_idx + 1,
                "status": status,
                "content-type": actual_ct,
            }
            if normalized is not None:
                step_out["body"] = normalized
            step_results.append(step_out)

            raw_cookies = []
            if hasattr(resp_headers, "get_all"):
                raw_cookies = resp_headers.get_all("Set-Cookie") or []
            if not raw_cookies:
                single = resp_headers.get("Set-Cookie") if hasattr(resp_headers, "get") else None
                if single:
                    raw_cookies = [single]
            for entry in raw_cookies:
                eq_idx = entry.find("=")
                if eq_idx < 0: continue
                key = entry[:eq_idx].strip()
                rest = entry[eq_idx + 1:].split(";")[0].strip()
                if key and rest:
                    cookies[key] = rest

            for state_key, cookie_name in step.get("storeCookies", {}).items():
                if cookie_name in cookies:
                    state[state_key] = cookies[cookie_name]

            store_paths = step.get("store", {})
            if store_paths:
                try:
                    response_obj = json.loads(resp_body)
                    for state_key, json_path in store_paths.items():
                        parts = json_path.lstrip("$.").split(".")
                        val = response_obj
                        for p in parts:
                            if isinstance(val, dict):
                                val = val.get(p)
                            else:
                                val = None
                                break
                        if val is not None:
                            state[state_key] = val
                except (json.JSONDecodeError, ValueError):
                    pass

            store_html = step.get("storeHtml", {})
            for state_key, pattern in store_html.items():
                m = re.search(pattern, resp_body)
                if m and m.lastindex and m.group(1):
                    state[state_key] = m.group(1)

        results.append({
            "id": tid,
            "stdout": json.dumps(step_results, sort_keys=True),
            "stderr": "",
            "returncode": 0,
        })

    json.dump(results, sys.stdout, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        json.dump([], sys.stdout)
