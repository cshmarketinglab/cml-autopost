"""매일 아침 실행: 오늘 쓰레드 3개 + (해당일이면) 캐러셀 원고·이미지 생성 → queue/YYYY-MM-DD.json"""
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


def plan_threads(cfg: dict, d: date) -> list[dict]:
    anchor = date.fromisoformat(cfg["carousel_anchor_date"])
    recruit_today = is_every_n(d, anchor, cfg["recruit_every_n_days"])
    plan = []
    for s in cfg["threads_slots"]:
        t = "recruit" if (recruit_today and s["slot"] == cfg["recruit_slot"]) else "empathy"
        plan.append({"slot": s["slot"], "type": t, "publish_at": at_kst(d, s["time"])})
    return plan


def gen_threads(cfg: dict, plan: list[dict], history: dict) -> list[dict]:
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


def gen_carousel(cfg: dict, d: date, history: dict) -> dict:
    import shutil

    from photos import fetch
    from render import render_carousel

    b, ds = cfg["brand"], cfg["design"]
    system = (PROMPT_DIR / "carousel.md").read_text(encoding="utf-8").format(
        brand_name=b["name"], topics="\n".join(f"- {t}" for t in cfg["carousel_topics"]),
        recent=_recent(history, "carousel_topics", 30),
    )
    user = "오늘 캐러셀 원고 작성해줘."
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

    # 슬라이드별 사진 (표지 세로, 본문 가로)
    img_dir = OUT_DIR / d.isoformat()
    src_dir = img_dir / "_src"
    used = set(history.get("photo_ids", []))
    credits = []
    targets = [("cover", data["cover"], "portrait")] + [(f"s{i+1}", s, "landscape") for i, s in enumerate(data["sections"])]
    for name, block, orient in targets:
        ph = fetch(block["photo_query"], src_dir / f"{name}.jpg", orient, used, ds["photo_fallbacks"])
        block["photo"] = ph["path"] if ph else None
        if ph:
            credits.append({"slide": name, "id": ph["id"], "photographer": ph["photographer"],
                            "url": ph["url"], "query": ph["query"]})

    images, overflow = render_carousel(data, ds, img_dir)
    shutil.rmtree(src_dir, ignore_errors=True)  # 원본 사진은 저장소에 안 남김

    caption = data["caption"].strip()
    if ds.get("photo_credit_in_caption") and credits:
        caption += "\n\nPhotos via Pexels"
    for block in [data["cover"], *data["sections"]]:
        block.pop("photo", None)
    return {
        "topic": data.get("topic", ""), "episode": episode, "kicker": data["kicker"],
        "cover": data["cover"], "sections": data["sections"], "caption": caption,
        "photos": credits, "missing_photos": len(targets) - len(credits), "overflow_slides": overflow,
        "images": [Path(p).relative_to(ROOT).as_posix() for p in images],
        "publish_at": at_kst(d, cfg["carousel_time"]),
        "approved": bool(cfg["auto_approve"]), "status": "pending",
    }


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
    if not data.get("caption"):
        p.append("caption 없음")
    return p


def main():
    cfg = load_config()
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else today_kst()
    qp = queue_path(d)
    if qp.exists() and "--force" not in sys.argv:
        print(f"이미 생성됨: {qp}")
        return
    history = read_json(HISTORY_FILE, {"threads_hooks": [], "carousel_topics": []})

    threads = gen_threads(cfg, plan_threads(cfg, d), history)
    queue = {"date": d.isoformat(), "threads": threads, "carousel": None}

    anchor = date.fromisoformat(cfg["carousel_anchor_date"])
    if d >= anchor and is_every_n(d, anchor, cfg["carousel_every_n_days"]):
        queue["carousel"] = gen_carousel(cfg, d, history)
        car = queue["carousel"]
        history["carousel_topics"].append(car["topic"])
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


if __name__ == "__main__":
    main()
