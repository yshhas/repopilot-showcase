"""
Live FastAPI smoke test for C3–C6 endpoints.

Usage (service must be running on base_url):
    python scripts/api_smoke_test.py
    python scripts/api_smoke_test.py --base-url http://127.0.0.1:8000
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def request_json(method, url, body=None, timeout=30, api_key=None):

    data = None

    headers = {"Accept": "application/json"}


    if api_key:

        headers["X-API-Key"] = api_key


    if body is not None:

        data = json.dumps(body).encode("utf-8")

        headers["Content-Type"] = "application/json"


    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )


    with urllib.request.urlopen(req, timeout=timeout) as resp:

        raw = resp.read().decode("utf-8")

        return resp.status, json.loads(raw) if raw else {}


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
    )

    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Only check GET /health (for Docker/CI without LLM)",
    )

    parser.add_argument(
        "--api-key",
        default=None,
        help="X-API-Key header (required when server API_KEY is set)",
    )

    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    api_key = args.api_key

    checks = []


    def record(name, ok, detail=""):

        checks.append((name, ok, detail))

        mark = "OK" if ok else "FAIL"

        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


    try:

        status, data = request_json("GET", base + "/health")

        record(
            "GET /health",
            status == 200 and data.get("status") == "ok",
            str(data),
        )

    except Exception as exc:

        record("GET /health", False, str(exc))

        print("\nSmoke test aborted: API not reachable.")

        sys.exit(1)

    if args.health_only:

        print("\nSummary: 1 / 1 passed (health-only)")

        sys.exit(0)


    task_id = None


    try:

        status, data = request_json(
            "POST",
            base + "/tasks",
            {"question": "api smoke test"},
            api_key=api_key,
        )

        task_id = data.get("task_id")

        record(
            "POST /tasks",
            status == 201 and bool(task_id),
            "task_id=" + str(task_id),
        )

    except Exception as exc:

        record("POST /tasks", False, str(exc))


    if task_id:

        try:

            status, data = request_json(
                "GET",
                base + "/tasks/" + task_id,
                api_key=api_key,
            )

            record(
                "GET /tasks/{task_id}",
                status == 200 and data.get("task_id") == task_id,
                "status=" + str(data.get("status")),
            )

        except Exception as exc:

            record("GET /tasks/{task_id}", False, str(exc))


        try:

            status, data = request_json(
                "GET",
                base + "/tasks/" + task_id + "/report",
                api_key=api_key,
            )

            record(
                "GET /tasks/{task_id}/report",
                status == 200 and "report" in data,
                "len=" + str(len(data.get("report", ""))),
            )

        except Exception as exc:

            record("GET /tasks/{task_id}/report", False, str(exc))


        try:

            status, data = request_json(
                "GET",
                base + "/tasks/" + task_id + "/confirm/pending",
                api_key=api_key,
            )

            record(
                "GET /tasks/{task_id}/confirm/pending",
                status == 200 and "pending" in data,
                "pending=" + str(data.get("pending")),
            )

        except Exception as exc:

            record(
                "GET /tasks/{task_id}/confirm/pending",
                False,
                str(exc),
            )


        try:

            request_json(
                "POST",
                base + "/tasks/" + task_id + "/confirm",
                {"confirmed": True},
                api_key=api_key,
            )

            record(
                "POST /tasks/{task_id}/confirm (idle)",
                False,
                "expected 409 but got success",
            )

        except urllib.error.HTTPError as exc:

            record(
                "POST /tasks/{task_id}/confirm (idle)",
                exc.code == 409,
                "http " + str(exc.code),
            )

        except Exception as exc:

            record(
                "POST /tasks/{task_id}/confirm (idle)",
                False,
                str(exc),
            )


    failed = [name for name, ok, _ in checks if not ok]

    print("\nSummary:", len(checks) - len(failed), "/", len(checks), "passed")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":

    main()
