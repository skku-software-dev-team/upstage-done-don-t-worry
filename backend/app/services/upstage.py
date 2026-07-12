import httpx

from app.core.config import settings

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"


async def embed_text(text: str) -> list[float]:
    """Solar embedding via Upstage API (4096-dim)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{UPSTAGE_BASE_URL}/solar/embeddings",
            headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
            json={"model": "solar-embedding-1-large", "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def chat_completion(messages: list[dict], context: str = "") -> str:
    """Solar chat via Upstage API."""
    system_prompt = (
        "당신은 정보보호 인증(ISMS-P, CSAP, ISO27001) 전문 어시스턴트입니다. "
        "주어진 조항 내용을 바탕으로 정확하고 구체적으로 답변하세요.\n\n"
        f"참고 조항:\n{context}" if context else
        "당신은 정보보호 인증 전문 어시스턴트입니다."
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{UPSTAGE_BASE_URL}/solar/chat/completions",
            headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
            json={
                "model": "solar-pro",
                "messages": [{"role": "system", "content": system_prompt}, *messages],
                "temperature": 0.3,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def parse_document(file_bytes: bytes, filename: str) -> dict:
    """Document AI parsing via Upstage API."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{UPSTAGE_BASE_URL}/document-ai/ocr",
            headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
            files={"document": (filename, file_bytes, "application/pdf")},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()
