"""Pexels 무료 사진 검색·다운로드.
- 슬라이드마다 Claude가 만든 영어 검색어로 검색
- 과거에 쓴 사진(history)·같은 캐러셀 안에서 쓴 사진은 제외
- 결과 없으면 예비 검색어 → 그래도 없으면 None (사진 없는 레이아웃으로 렌더)
- 무료 한도: 시간당 200회, 월 20,000회 → 캐러셀 1개당 약 6~10회 사용
"""
import os
import random
from pathlib import Path

import requests

API = "https://api.pexels.com/v1/search"
TIMEOUT = 30


def _search(query: str, orientation: str) -> list[dict]:
    r = requests.get(API, headers={"Authorization": os.environ["PEXELS_API_KEY"]},
                     params={"query": query, "orientation": orientation, "per_page": 30, "size": "medium"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("photos", [])


def _download(photo: dict, dest: Path, width: int) -> Path:
    url = f"{photo['src']['original']}?auto=compress&cs=tinysrgb&w={width}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def fetch(query: str, dest: Path, orientation: str, used: set[int], fallbacks: list[str],
          width: int = 1600) -> dict | None:
    """사진 1장 받아 dest에 저장. 반환: {id, path, photographer, url} 또는 None"""
    if os.environ.get("MOCK_PHOTOS"):  # 로컬 테스트: 폴더의 사진을 순서대로 사용
        pool = sorted(Path(os.environ["MOCK_PHOTOS"]).glob("*.jpg"))
        pick = pool[len(used) % len(pool)]
        used.add(len(used) + 1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pick.read_bytes())
        return {"id": 0, "path": str(dest), "photographer": "mock", "url": "", "query": query}
    if not os.environ.get("PEXELS_API_KEY"):
        print("PEXELS_API_KEY 없음 — 사진 없이 렌더")
        return None

    for q in [query, *fallbacks]:
        try:
            photos = [p for p in _search(q, orientation) if p["id"] not in used]
        except requests.RequestException as e:
            print(f"Pexels 검색 실패({q}): {e}")
            continue
        if not photos:
            continue
        # 상위 결과만 쓰면 다른 계정과 겹치기 쉬움 → 상위 12개 중 무작위
        photo = random.choice(photos[:12])
        try:
            _download(photo, dest, width)
        except requests.RequestException as e:
            print(f"사진 다운로드 실패: {e}")
            continue
        used.add(photo["id"])
        return {"id": photo["id"], "path": str(dest), "photographer": photo.get("photographer", ""),
                "url": photo.get("url", ""), "query": q}
    return None
