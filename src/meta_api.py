"""Threads / Instagram Graph API 발행.

Threads   : graph.threads.net  (2단계: 컨테이너 생성 → publish)
Instagram : graph.instagram.com (Instagram API with Instagram Login, 프로페셔널 계정 필요)
            캐러셀 = 이미지별 child 컨테이너 → CAROUSEL 컨테이너 → media_publish
"""
import os
import time

import requests

THREADS_BASE = "https://graph.threads.net/v1.0"
IG_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
IG_BASE = f"https://graph.instagram.com/{IG_VERSION}"
TIMEOUT = 60


class MetaError(RuntimeError):
    pass


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        raise MetaError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        raise MetaError(f"HTTP {r.status_code}: {data.get('error', data)}")
    return data


# ── Threads ─────────────────────────────────────
def threads_publish_text(text: str) -> str:
    if os.environ.get("DRY_RUN"):
        print(f"[DRY_RUN] Threads 발행:\n{text}\n")
        return "dry-run"
    token = os.environ["THREADS_ACCESS_TOKEN"]
    uid = os.environ.get("THREADS_USER_ID", "me")
    c = _check(requests.post(f"{THREADS_BASE}/{uid}/threads",
                             data={"media_type": "TEXT", "text": text, "access_token": token}, timeout=TIMEOUT))
    time.sleep(5)  # Meta 권장: 생성 후 잠시 대기
    p = _check(requests.post(f"{THREADS_BASE}/{uid}/threads_publish",
                             data={"creation_id": c["id"], "access_token": token}, timeout=TIMEOUT))
    return p["id"]


# ── Instagram ───────────────────────────────────
def _ig_wait_ready(container_id: str, token: str, tries: int = 20) -> None:
    for _ in range(tries):
        s = _check(requests.get(f"{IG_BASE}/{container_id}",
                                params={"fields": "status_code,status", "access_token": token}, timeout=TIMEOUT))
        code = s.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise MetaError(f"컨테이너 {container_id} 실패: {s}")
        time.sleep(6)
    raise MetaError(f"컨테이너 {container_id} 처리 시간 초과")


def ig_publish_carousel(image_urls: list[str], caption: str) -> str:
    if os.environ.get("DRY_RUN"):
        print(f"[DRY_RUN] 인스타 캐러셀 {len(image_urls)}장:\n" + "\n".join(image_urls) + f"\n캡션:\n{caption}\n")
        return "dry-run"
    if not 2 <= len(image_urls) <= 10:
        raise MetaError(f"캐러셀 이미지 수 {len(image_urls)} (2~10장 필요)")
    token = os.environ["IG_ACCESS_TOKEN"]
    uid = os.environ["IG_USER_ID"]

    children = []
    for url in image_urls:
        c = _check(requests.post(f"{IG_BASE}/{uid}/media",
                                 data={"image_url": url, "is_carousel_item": "true", "access_token": token},
                                 timeout=TIMEOUT))
        children.append(c["id"])
    for cid in children:
        _ig_wait_ready(cid, token)

    parent = _check(requests.post(f"{IG_BASE}/{uid}/media",
                                  data={"media_type": "CAROUSEL", "children": ",".join(children),
                                        "caption": caption, "access_token": token}, timeout=TIMEOUT))
    _ig_wait_ready(parent["id"], token)
    p = _check(requests.post(f"{IG_BASE}/{uid}/media_publish",
                             data={"creation_id": parent["id"], "access_token": token}, timeout=TIMEOUT))
    return p["id"]
