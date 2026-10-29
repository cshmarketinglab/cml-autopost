"""Claude API 호출 → JSON 파싱 (실패 시 재시도)."""
import json
import os
import re

import anthropic


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON 없음")
    return json.loads(text[start : end + 1])


def ask_json(model: str, system: str, user: str, max_tokens: int = 4000, retries: int = 2) -> dict:
    if os.environ.get("MOCK_LLM"):  # 로컬 테스트용
        from mock_llm import mock_response
        return mock_response(user)

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    # 도구 호출 형식으로 받으면 API가 JSON 구조를 보장 → 본문 속 따옴표 등으로 깨지는 문제 방지
    tool = {"name": "output", "description": "요청된 JSON 결과를 그대로 담아 제출",
            "input_schema": {"type": "object", "additionalProperties": True}}
    extra = {"system": system} if system else {}
    last_err = None
    # 일부 모델은 도구 강제(tool_choice=tool)를 지원하지 않음 → 자동 선택 + 지시문으로 도구 사용 유도
    ask = user + "\n\n(결과는 반드시 output 도구를 호출해서 제출할 것. 본문 텍스트로 쓰지 말 것.)"
    for _ in range(retries + 1):
        try:
            msg = client.messages.create(
                model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": ask}],
                tools=[tool], tool_choice={"type": "auto"}, **extra)
            for b in msg.content:
                if b.type == "tool_use" and isinstance(b.input, dict) and b.input:
                    return b.input
            text = "".join(getattr(b, "text", "") for b in msg.content)
            return _extract_json(text)  # 도구 대신 글로 답한 경우
        except anthropic.BadRequestError as e:
            # 도구 자체를 못 쓰는 경우 → 예전 방식(텍스트 JSON)으로 한 번 더
            last_err = e
            try:
                msg = client.messages.create(model=model, max_tokens=max_tokens,
                                             messages=[{"role": "user", "content": user}], **extra)
                return _extract_json("".join(getattr(b, "text", "") for b in msg.content))
            except Exception as e2:  # noqa: BLE001
                last_err = e2
        except anthropic.APIStatusError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Claude 응답 JSON 파싱 실패: {last_err}")


def pick_image(model: str, context: str, thumb_urls: list[str]) -> int:
    """후보 썸네일 중 슬라이드 내용과 가장 맞는 사진 번호(0부터). 맞는 게 없으면 -1. 실패 시 0."""
    if os.environ.get("MOCK_LLM") or not thumb_urls:
        return 0
    content = []
    for i, u in enumerate(thumb_urls):
        content += [{"type": "text", "text": f"[{i}]"}, {"type": "image", "source": {"type": "url", "url": u}}]
    content.append({"type": "text", "text": (
        "인스타 캐러셀 한 장에 들어갈 배경 사진을 고른다. 이 장의 내용:\n" + context +
        "\n\n기준: ① 내용의 장면·사물·분위기와 직접 맞을 것(예: '매장 입구'면 가게 문·외관, '자연광'이면 밝은 낮 빛, '손'이면 손이 보일 것) "
        "② 큰 글자·로고·워터마크 없을 것 ③ 한국 동네 가게 콘텐츠에 어색하지 않을 것.\n"
        "가장 맞는 사진 번호 하나만 숫자로 답해. 기준 ①을 만족하는 사진이 하나도 없으면 -1.")})
    try:
        msg = anthropic.Anthropic().messages.create(
            model=model, max_tokens=10, messages=[{"role": "user", "content": content}])
        m = re.search(r"-?\d+", "".join(b.text for b in msg.content if b.type == "text"))
        n = int(m.group()) if m else 0
        return n if -1 <= n < len(thumb_urls) else 0
    except Exception as e:  # noqa: BLE001  — 검수 실패해도 생성은 계속
        print(f"사진 검수 실패(첫 후보 사용): {e}")
        return 0
