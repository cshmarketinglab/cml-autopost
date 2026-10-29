"""매일 아침 실행: 오늘 쓰레드 3개 + (해당일이면) 캐러셀 원고·이미지 생성 → queue/YYYY-MM-DD.json"""
import os
import sys
from datetime import date
from pathlib import Path

from common import (OUT_DIR, PROMPT_DIR, ROOT, HISTORY_FILE, at_kst, is_every_n, load_config,
                    queue_path, read_json, today_kst, write_json)
from llm import ask_json

THREADS_LIMIT = 500  # Meta 쓰레드 본문 한도


def _recent(history: dict, key: str, n: int = 40) -> str:
    items = history.get(key, [])[-n:]
    return "\n".join(f"- {x}" for x in items) or "- (없음)"


def load_news(d: date) -> list[dict]:
    """news.py가 같은 날 저장한 선별 기사 (없으면 빈 목록)"""
    return read_json(ROOT / "news" / f"{d.isoformat()}.json", []) or []


def plan_threads(cfg: dict, d: date, has_news: bool = False) -> list[dict]:
    anchor = date.fromisoformat(cfg["carousel_anchor_date"])
    recruit_today = is_every_n(d, anchor, cfg["recruit_every_n_days"])
    plan = []
    for s in cfg["threads_slots"]:
        t = "recruit" if (recruit_today and s["slot"] == cfg["recruit_slot"]) else "empathy"
        plan.append({"slot": s["slot"], "type": t, "publish_at": at_kst(d, s["time"])})
    # 뉴스가 있으면 첫 공감글 하나를 '뉴스 공감글'로 (config의 news_post: false로 끌 수 있음)
    if has_news and cfg.get("news_post", True):
        for p in plan:
            if p["type"] == "empathy":
                p["type"] = "news"
                break
    return plan


def gen_threads(cfg: dict, plan: list[dict], history: dict, news: list | None = None) -> list[dict]:
    b = cfg["brand"]
    system = (PROMPT_DIR / "threads.md").read_text(encoding="utf-8").format(
        brand_name=b["name"], brand_cta=b["cta"], copy_main=b["copy_main"], copy_sub=b["copy_sub"],
        facts="\n".join(f"- {f}" for f in b["facts"]), recent=_recent(history, "threads_hooks"),
    )
    want = ", ".join(p["type"] for p in plan)
    user = (
        f"오늘 쓸 글 {len(plan)}개. 순서대로 type: [{want}]\n"
        f"공감글 소재 후보(서로 다른 걸로 골라): {', '.join(cfg['empathy_pillars'])}\n"
        "각 글은 서로 소재·구조·첫 줄 형식이 달라야 해."
    )
    if news and any(p["type"] == "news" for p in plan):
        cands = [n for n in news if n.get("category") != "트렌드"] or news
        user += "\n\n[오늘 뉴스 — type=news 글은 이 중 하나로]\n" + "\n".join(
            f"- ({n.get('category', '')}) {n['title']} / 요약: {n.get('summary', '')} / 소재 힌트: {n.get('idea', '')}"
            for n in cands[:5])
    for attempt in range(3):
        data = ask_json(cfg["model"], system, user)
        posts = data.get("posts", [])
        too_long = [i for i, p in enumerate(posts) if len(p.get("text", "")) > THREADS_LIMIT]
        if len(posts) == len(plan) and not too_long:
            break
        user += f"\n\n(직전 결과 문제: 개수 {len(posts)}/{len(plan)}, 500자 초과 {too_long}. 다시 써.)"
    else:
        raise RuntimeError("쓰레드 글 생성 조건 미충족")

    out = []
    for p, post in zip(plan, posts):
        out.append({**p, "pillar": post.get("pillar", ""), "text": post["text"].strip(),
                    "approved": bool(cfg["auto_approve"]), "status": "pending"})
    return out


def pick_carousel_news(cfg: dict, d: date, history: dict) -> dict | None:
    """뉴스 중 '캐러셀감'으로 표시된 기사 1개. 최근 2일 안에 뉴스 캐러셀이 있었으면 건너뜀(너무 잦지 않게).
    같은 날 재생성은 허용."""
    if not cfg.get("news_carousel", True):
        return None
    last = history.get("last_carousel_news_date")
    if last and last != d.isoformat() and (d - date.fromisoformat(last)).days <= cfg.get("news_carousel_gap_days", 2):
        return None
    return next((n for n in load_news(d) if n.get("carousel") and n.get("angle")), None)


def gen_carousel(cfg: dict, d: date, history: dict, news_item: dict | None = None) -> dict:
    import shutil

    from photos import fetch
    from render import render_carousel

    b, ds = cfg["brand"], cfg["design"]
    system = (PROMPT_DIR / "carousel.md").read_text(encoding="utf-8").format(
        brand_name=b["name"], topics="\n".join(f"- {t}" for t in cfg["carousel_topics"]),
        recent=_recent(history, "carousel_topics", 30),
    )
    user = "오늘 캐러셀 원고 작성해줘."
    if news_item:
        user += (
            "\n\n[오늘은 뉴스 기반 회차] 아래 뉴스를 계기로, 사장님이 이 변화에 맞춰 '할 일' 중심으로 써라. 주제 후보 목록은 무시."
            f"\n- 기사: {news_item['title']}\n- 요약: {news_item.get('summary', '')}\n- 관점: {news_item['angle']}"
            "\n- 기사 제목·요약 밖의 금액·비율·날짜·자격 조건은 절대 쓰지 마(원문을 못 봤다). 조건이 중요하면 '공식 공고에서 확인'으로."
            "\n- 정부·정치 평가 금지. 첫 section에서 무슨 변화인지 한 문장으로만 짚고 바로 실천 팁으로."
        )
    for _ in range(3):
        data = ask_json(cfg["model"], system, user, max_tokens=4000)
        problems = check_carousel(data)
        if not problems:
            break
        user += "\n\n(직전 결과 문제: " + " / ".join(problems) + " — 고쳐서 다시 전체 출력)"
    else:
        raise RuntimeError(f"캐러셀 원고 조건 미충족: {problems}")

    # 회차 번호: 같은 날짜 재생성이면 기존 번호 유지
    prev = (read_json(queue_path(d)) or {}).get("carousel") or {}
    episode = prev.get("episode") or ds["series_start"] + history.get("carousel_count", 0)
    data["kicker"] = ds["series"].format(n=episode)
    if news_item:  # 뉴스 회차는 표지에 '· 이슈 특강' 표시
        data["kicker"] += ds.get("news_suffix", " · 이슈 특강")

    # 슬라이드별 사진 (표지 세로, 본문 가로)
    img_dir = OUT_DIR / d.isoformat()
    src_dir = img_dir / "_src"
    used = set(history.get("photo_ids", []))
    credits = []
    targets = [("cover", data["cover"], "portrait")] + [(f"s{i+1}", s, "landscape") for i, s in enumerate(data["sections"])]
    for name, block, orient in targets:
        ctx = (block.get("title") or block.get("heading", "")).replace("\n", " ") + "\n" + block.get("body", "").replace("**", "")
        ph = fetch(block["photo_query"], src_dir / f"{name}.jpg", orient, used, ds["photo_fallbacks"],
                   context=ctx, model=cfg["model"])
        block["photo"] = ph["path"] if ph else None
        if ph:
            credits.append({"slide": name, "id": ph["id"], "provider": ph["provider"], "photographer": ph["photographer"],
                            "url": ph["url"], "query": ph["query"]})

    images, overflow = render_carousel(data, ds, img_dir)
    shutil.rmtree(src_dir, ignore_errors=True)  # 원본 사진은 저장소에 안 남김

    if news_item:
        data["news_source"] = news_item.get("source") or "관련 기사"
    caption = build_caption(data, cfg)
    kw_line = (cfg.get("comment_dm") or {}).get("caption_line", "").strip()
    if (cfg.get("comment_dm") or {}).get("enabled") and kw_line:
        # 해시태그 줄 바로 앞에 '댓글 키워드' 안내 삽입 (Meta 자동 DM과 짝)
        lines = caption.split("\n")
        at = next((i for i, l in enumerate(lines) if l.strip().startswith("#")), len(lines))
        lines[at:at] = [kw_line, ""]
        caption = "\n".join(lines)
    if ds.get("photo_credit_in_caption") and credits:
        names = sorted({c["provider"] for c in credits if c["provider"] != "mock"}) or ["stock"]
        caption += "\n\nPhotos via " + " & ".join(names)
    for block in [data["cover"], *data["sections"]]:
        block.pop("photo", None)
    return {
        "topic": data.get("topic", ""), "episode": episode, "kicker": data["kicker"],
        "news_based": news_item["title"] if news_item else "",
        "cover": data["cover"], "sections": data["sections"], "caption": caption,
        "photos": credits, "missing_photos": len(targets) - len(credits), "overflow_slides": overflow,
        "images": [Path(p).relative_to(ROOT).as_posix() for p in images],
        "publish_at": at_kst(d, cfg["carousel_time"]),
        "approved": bool(cfg["auto_approve"]), "status": "pending",
    }


def build_caption(data: dict, cfg: dict) -> str:
    """모바일용 캡션: 짧은 줄 + 빈 줄로 블록 구분. 본문은 슬라이드 제목으로 조립(항상 짧고 일관됨)."""
    secs = data["sections"]
    tips = "\n".join(f"✔️ {s['heading'].strip()}" for s in secs[:-1])
    hw = secs[-1]["heading"].strip()
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    tags = " ".join(t if t.startswith("#") else f"#{t}" for t in tags[:8])
    blocks = [
        data["hook"].strip(),
        f"{data.get('kicker', '').strip()} 정리\n{tips}",
        f"📝 오늘의 숙제\n{hw}",
        (f"📰 참고: {data['news_source']} 보도 · 세부 조건은 공식 공고를 꼭 확인하세요"
         if data.get("news_source") else ""),
        cfg["design"].get("caption_save_line", "저장해두고 필요할 때 꺼내 보세요"),
        tags,
    ]
    return "\n\n".join(b for b in blocks if b)


def check_carousel(data: dict) -> list[str]:
    import re
    p = []
    cover = data.get("cover") or {}
    lines = (cover.get("title") or "").split("\n")
    if not cover.get("title") or len(lines) > 2 or any(len(x) > 13 for x in lines):
        p.append("cover.title은 두 줄 이내, 한 줄 12자 이내")
    if not cover.get("photo_query"):
        p.append("cover.photo_query 없음")
    secs = data.get("sections") or []
    if not 4 <= len(secs) <= 8:
        p.append(f"sections {len(secs)}개 (4~8개 필요 — 인스타 API 캐러셀 최대 10장)")
    for i, s in enumerate(secs, 1):
        body = s.get("body", "")
        n = len(re.sub(r"\*\*", "", body))
        if len(s.get("heading", "")) > 22:
            p.append(f"{i}번 heading 22자 초과")
        if not 100 <= n <= 175:
            p.append(f"{i}번 body {n}자 (120~160자로)")
        if body.count("**") != 2:
            p.append(f"{i}번 **강조** 정확히 1개 필요")
        if not s.get("photo_query"):
            p.append(f"{i}번 photo_query 없음")
    hook = (data.get("hook") or "").strip().split("\n")
    if not data.get("hook") or len(hook) > 2 or any(len(x) > 24 for x in hook):
        p.append("hook은 2줄 이내, 한 줄 20자 이내")
    if not data.get("hashtags"):
        p.append("hashtags 없음")
    return p


def main():
    cfg = load_config()
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else today_kst()
    qp = queue_path(d)
    if qp.exists() and "--force" not in sys.argv:
        print(f"이미 생성됨: {qp}")
        return
    history = read_json(HISTORY_FILE, {"threads_hooks": [], "carousel_topics": []})

    news = load_news(d)
    threads = gen_threads(cfg, plan_threads(cfg, d, has_news=bool(news)), history, news)
    queue = {"date": d.isoformat(), "threads": threads, "carousel": None}

    anchor = date.fromisoformat(cfg["carousel_anchor_date"])
    scheduled = d >= anchor and is_every_n(d, anchor, cfg["carousel_every_n_days"])
    # 격일 정기 캐러셀 + 중요 뉴스가 있는 날은 쉬는 날이어도 뉴스 캐러셀 추가
    news_item = pick_carousel_news(cfg, d, history)
    if scheduled or news_item:
        queue["carousel"] = gen_carousel(cfg, d, history, news_item)
        car = queue["carousel"]
        history["carousel_topics"].append(car["topic"])
        if car.get("news_based"):
            history["last_carousel_news_date"] = d.isoformat()
        prev_ep = ((read_json(qp) or {}).get("carousel") or {}).get("episode")
        if car["episode"] != prev_ep:  # 재생성 시 회차 중복 증가 방지
            history["carousel_count"] = history.get("carousel_count", 0) + 1
        history["photo_ids"] = (history.get("photo_ids", []) + [x["id"] for x in car["photos"] if x["id"]])[-600:]

    history["threads_hooks"] += [t["text"].splitlines()[0][:60] for t in threads]
    history["threads_hooks"] = history["threads_hooks"][-120:]
    history["carousel_topics"] = history["carousel_topics"][-60:]
    write_json(qp, queue)
    write_json(HISTORY_FILE, history)
    print(f"생성 완료: {qp}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:  # 워크플로에 '새로 생성됨' 알림 → 이때만 검수 이슈 생성
        with open(out, "a") as f:
            f.write("generated=true\n")


if __name__ == "__main__":
    main()
