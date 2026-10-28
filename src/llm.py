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
    last_err = None
    for _ in range(retries + 1):
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return _extract_json(text)
        except Exception as e:  # noqa: BLE001
            last_err = e
            user += "\n\n(직전 응답이 JSON 형식이 아니었음. 반드시 JSON 객체 하나만 출력할 것.)"
    raise RuntimeError(f"Claude 응답 JSON 파싱 실패: {last_err}")
