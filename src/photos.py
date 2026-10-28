"""무료 스톡 사진 검색·다운로드 (Pixabay 기본, Pexels 키가 있으면 Pexels 우선).
- 슬라이드마다 Claude가 만든 영어 검색어로 검색
- 과거에 쓴 사진(history)·같은 캐러셀 안에서 쓴 사진은 제외
- 결과 없으면 예비 검색어 → 다른 사진 서비스 → 그래도 없으면 None (사진 없는 레이아웃으로 렌더)
- Pixabay: 무료 키, 60초당 100회. 미리보기 URL은 24시간 뒤 만료 → 즉시 다운로드해서 렌더에만 사용
- Pexels : 2026-09-30부터 신규 키 발급 중단 (기존 키는 동작)
"""
import os
import random
from pathlib import Path

import requests

TIMEOUT = 30


# ── Pixabay ─────────────────────────────────────
def _pixabay(query: str, orientation: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/", timeout=TIMEOUT, params={
        "key": os.environ["PIXABAY_API_KEY"], "q": query[:100], "image_type": "photo",
        "orientation": "vertical" if orientation == "portrait" else "horizontal",
        "per_page": 30, "safesearch": "true", "min_width": 1080,
    })
    r.raise_for_status()
    return [{"id": f"pb:{h['id']}", "url": h.get("pageURL", ""), "photographer": h.get("user", ""),
             "download": h.get("largeImageURL") or h.get("webformatURL"), "provider": "Pixabay"}
            for h in r.json().get("hits", [])]


# ── Pexels ──────────────────────────────────────
def _pexels(query: str, orientation: str) -> list[dict]:
    r = requests.get("https://api.pexels.com/v1/search", timeout=TIMEOUT,
                     headers={"Authorization": os.environ["PEXELS_API_KEY"]},
                     params={"query": query, "orientation": orientation, "per_page": 30, "size": "medium"})
    r.raise_for_status()
    return [{"id": f"px:{p['id']}", "url": p.get("url", ""), "photographer": p.get("photographer", ""),
             "download": f"{p['src']['original']}?auto=compress&cs=tinysrgb&w=1600", "provider": "Pexels"}
            for p in r.json().get("photos", [])]


def _providers():
    out = []
    if os.environ.get("PEXELS_API_KEY"):
        out.append(("Pexels", _pexels))
    if os.environ.get("PIXABAY_API_KEY"):
        out.append(("Pixabay", _pixabay))
    return out


def fetch(query: str, dest: Path, orientation: str, used: set, fallbacks: list[str]) -> dict | None:
    """사진 1장 받아 dest에 저장. 반환: {id, path, photographer, url, provider, query} 또는 None"""
    if os.environ.get("MOCK_PHOTOS"):  # 로컬 테스트: 폴더의 사진을 순서대로 사용
        pool = sorted(Path(os.environ["MOCK_PHOTOS"]).glob("*.jpg"))
        pick = pool[len(used) % len(pool)]
        used.add(f"mock:{len(used) + 1}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pick.read_bytes())
        return {"id": "", "path": str(dest), "photographer": "mock", "url": "", "provider": "mock", "query": query}

    providers = _providers()
    if not providers:
        print("사진 API 키 없음(PIXABAY_API_KEY / PEXELS_API_KEY) — 사진 없이 렌더")
        return None

    for name, search in providers:
        for q in [query, *fallbacks]:
            try:
                photos = [p for p in search(q, orientation) if p["id"] not in used and p["download"]]
            except requests.RequestException as e:
                print(f"{name} 검색 실패({q}): {e}")
                break  # 이 서비스 장애 → 다음 서비스로
            if not photos:
                continue
            # 상위 결과만 쓰면 다른 계정과 겹치기 쉬움 → 상위 12개 중 무작위
            photo = random.choice(photos[:12])
            try:
                r = requests.get(photo["download"], timeout=TIMEOUT)
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"{name} 다운로드 실패: {e}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            used.add(photo["id"])
            return {"id": photo["id"], "path": str(dest), "photographer": photo["photographer"],
                    "url": photo["url"], "provider": name, "query": q}
    return None
