"""장기 토큰(60일) 연장. 결과 토큰을 stdout에 'NAME=값' 형태로 출력하면 워크플로가 GitHub Secret을 갱신한다.
토큰은 발급 후 24시간 지나야 연장 가능하고, 만료 전에만 연장된다 → 10일마다 실행."""
import os
import sys

import requests

ENDPOINTS = {
    "THREADS_ACCESS_TOKEN": ("https://graph.threads.net/refresh_access_token", "th_refresh_token"),
    "IG_ACCESS_TOKEN": ("https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
}


def main() -> int:
    failed = 0
    for name, (url, grant) in ENDPOINTS.items():
        tok = os.environ.get(name)
        if not tok:
            print(f"# {name} 없음 — 건너뜀", file=sys.stderr)
            continue
        r = requests.get(url, params={"grant_type": grant, "access_token": tok}, timeout=60)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.ok and data.get("access_token"):
            days = int(data.get("expires_in", 0)) // 86400
            print(f"# {name} 연장 완료 (약 {days}일)", file=sys.stderr)
            print(f"{name}={data['access_token']}")
        else:
            failed += 1
            print(f"# {name} 연장 실패: HTTP {r.status_code} {str(data)[:200]}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
