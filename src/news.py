"""자영업·마케팅 관련 뉴스 수집 → Claude가 골라 요약 → GitHub 이슈 본문 출력.

소스: 네이버 뉴스 검색 API(키 있으면) → 없으면 구글 뉴스 RSS(키 불필요)
  python news.py 2026-10-29      → 이슈 본문을 stdout으로, 본 기사 기록은 news_seen.json에 저장
"""
import html
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from common import ROOT, load_config, read_json, today_kst, write_json
from llm import ask_json

SEEN_FILE = ROOT / "news_seen.json"
TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (cml-autopost news digest)"}


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def naver(q: str) -> list[dict]:
    r = requests.get("https://openapi.naver.com/v1/search/news.json", timeout=TIMEOUT,
                     params={"query": q, "display": 30, "sort": "date"},
                     headers={"X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
                              "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"]})
    r.raise_for_status()
    return [{"title": _clean(i["title"]), "url": i.get("originallink") or i["link"],
             "desc": _clean(i.get("description", ""))[:200], "source": "",
             "at": parsedate_to_datetime(i["pubDate"])} for i in r.json().get("items", [])]


def google(q: str) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote(q + ' when:2d')}&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        title = _clean(it.findtext("title", ""))
        src = _clean(it.findtext("source", ""))
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        try:
            at = parsedate_to_datetime(it.findtext("pubDate", ""))
        except (TypeError, ValueError):
            continue
        out.append({"title": title, "url": it.findtext("link", ""), "desc": "", "source": src, "at": at})
    return out


DEFAULT_NEWS = {
    # config.yaml에 news: 항목을 만들면 그걸 우선 사용
    "keywords": ["소상공인", "자영업자", "소상공인 지원사업", "네이버 플레이스", "배달앱 수수료",
                 "외식업 트렌드", "최저임금 자영업", "인스타그램 알고리즘", "AI 검색 마케팅"],
    "hours": 36,
    "max_items": 8,
}


def collect(cfg: dict) -> list[dict]:
    ncfg = {**DEFAULT_NEWS, **(cfg.get("news") or {})}
    fetch = naver if os.environ.get("NAVER_CLIENT_ID") else google
    since = datetime.now(timezone.utc) - timedelta(hours=ncfg.get("hours", 36))
    seen = set(read_json(SEEN_FILE, []))
    items, titles = [], set()
    for q in ncfg["keywords"]:
        try:
            got = fetch(q)
        except Exception as e:  # noqa: BLE001 — 키워드 하나 실패해도 계속
            print(f"[{q}] 수집 실패: {e}", file=sys.stderr)
            continue
        for a in got:
            key = re.sub(r"\W", "", a["title"])[:40]
            if a["at"] < since or a["url"] in seen or key in titles:
                continue
            titles.add(key)
            a["keyword"] = q
            items.append(a)
    items.sort(key=lambda a: a["at"], reverse=True)
    return items[:80]


PROMPT = """너는 동네 식당·카페·펍·숙박업 사장님 대상 마케팅 프리랜서의 아침 뉴스 비서다.
아래 기사 목록(제목·요약만 있음)에서 이 사람에게 쓸모 있는 기사를 최대 {n}개 골라라.

[우선순위]
1. 사장님 매출·비용에 직접 영향: 소상공인 지원사업·정책, 최저임금, 배달앱·플랫폼 수수료, 카드수수료, 임대료
2. 마케팅 채널 변화: 네이버 플레이스·지도·검색, 인스타·쓰레드, 리뷰 정책, AI 검색
3. 외식·숙박·상권 트렌드
제외: 단순 홍보성 보도자료, 특정 업체 광고, 같은 사건 중복, 정치 공방, 사건사고

[규칙]
- 요약은 주어진 제목·요약에 있는 내용만. 없는 수치·날짜·조건을 지어내지 마. 확실하지 않으면 "자세한 조건은 원문 확인".
- why: 이 사람(마케터) 입장에서 왜 중요한지 한 줄.
- idea: 이 뉴스로 쓸 수 있는 쓰레드 공감글 소재 한 줄 (반말, 선택. 억지면 빈 문자열).

[기사 목록]
{items}

[출력] JSON만:
{{"picks": [{{"i": 번호, "category": "정책|채널|트렌드", "summary": "2문장 이내", "why": "...", "idea": "..."}}]}}"""


def build_body(d: date, picks: list[dict], items: list[dict], src_name: str) -> str:
    lines = [f"## {d.isoformat()} 자영업·마케팅 뉴스", f"_소스: {src_name} · 최근 기사 {len(items)}건 중 선별_", ""]
    for cat in ["정책", "채널", "트렌드"]:
        group = [p for p in picks if p.get("category") == cat]
        if not group:
            continue
        lines += [f"### {'💰' if cat == '정책' else '📱' if cat == '채널' else '📈'} {cat}", ""]
        for p in group:
            a = items[p["i"]]
            src = f" · {a['source']}" if a["source"] else ""
            lines += [f"**[{a['title']}]({a['url']})**{src}",
                      f"- {p['summary']}", f"- 👉 {p['why']}"]
            if p.get("idea"):
                lines.append(f"- ✍️ 소재: {p['idea']}")
            lines.append("")
    lines += ["---", "요약은 기사 제목·발췌 기반이라 세부 조건은 원문을 꼭 확인하세요."]
    return "\n".join(lines)


def main():
    cfg = load_config()
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else today_kst()
    items = collect(cfg)
    if not items:
        print("새 기사 없음", file=sys.stderr)
        return
    listing = "\n".join(f"[{i}] {a['title']} ({a['source'] or a['keyword']}) {a['desc']}" for i, a in enumerate(items))
    data = ask_json(cfg["model"], "", PROMPT.format(n={**DEFAULT_NEWS, **(cfg.get("news") or {})}["max_items"], items=listing), max_tokens=3000)
    picks = [p for p in data.get("picks", []) if isinstance(p.get("i"), int) and 0 <= p["i"] < len(items)]
    if not picks:
        print("선별된 기사 없음", file=sys.stderr)
        return
    src_name = "네이버 뉴스" if os.environ.get("NAVER_CLIENT_ID") else "구글 뉴스"
    print(build_body(d, picks, items, src_name))
    # 초안 생성(generate.py)이 쓰레드 '뉴스 공감글' 재료로 사용
    write_json(ROOT / "news" / f"{d.isoformat()}.json", [
        {"category": p.get("category", ""), "title": items[p["i"]]["title"], "url": items[p["i"]]["url"],
         "summary": p.get("summary", ""), "idea": p.get("idea", "")} for p in picks])
    seen = read_json(SEEN_FILE, []) + [a["url"] for a in items]
    write_json(SEEN_FILE, seen[-3000:])


if __name__ == "__main__":
    main()
