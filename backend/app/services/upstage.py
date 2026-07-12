import asyncio
import json
import re

import httpx

from app.core.config import settings

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"


async def embed_text(text: str, is_query: bool = False) -> list[float]:
    """Embed text with Solar. Use embedding-passage for stored docs,
    embedding-query for search queries (both 4096-dim).
    Retries on 429 with exponential backoff. Truncates to ~8000 chars."""
    model = "embedding-query" if is_query else "embedding-passage"
    payload = {"model": model, "input": text[:8000]}
    headers = {"Authorization": f"Bearer {settings.upstage_api_key}"}

    async with httpx.AsyncClient() as client:
        for attempt in range(5):
            resp = await client.post(
                f"{UPSTAGE_BASE_URL}/embeddings",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)  # 1,2,4,8,16s
                continue
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        # Final attempt raises if still failing
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def chat_completion(messages: list[dict], context: str = "") -> str:
    system_prompt = (
        "당신은 정보보호 인증(ISMS-P, CSAP, ISO27001) 전문 어시스턴트입니다. "
        "주어진 조항 내용을 바탕으로 정확하고 구체적으로 답변하세요.\n\n"
        f"참고 조항:\n{context}"
        if context
        else "당신은 정보보호 인증 전문 어시스턴트입니다."
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{UPSTAGE_BASE_URL}/chat/completions",
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
    """Document Parse API — uses async endpoint for large files, falls back to sync for small ones.
    Always returns a dict with an 'elements' key."""
    headers = {"Authorization": f"Bearer {settings.upstage_api_key}"}

    # Request markdown output explicitly so content.markdown is populated
    form_data = {"model": "document-parse", "output_formats": '["markdown", "text"]'}

    # Try sync first (≤50MB, ≤100 pages). If 413, fall back to async.
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{UPSTAGE_BASE_URL}/document-digitization",
            headers=headers,
            files={"document": (filename, file_bytes, "application/pdf")},
            data=form_data,
            timeout=180.0,
        )
        if resp.status_code != 413:
            resp.raise_for_status()
            return resp.json()

    # Async path — submit job, poll until done, then download batch results
    async with httpx.AsyncClient() as client:
        submit = await client.post(
            f"{UPSTAGE_BASE_URL}/document-digitization/async",
            headers=headers,
            files={"document": (filename, file_bytes, "application/pdf")},
            data=form_data,
            timeout=60.0,
        )
        submit.raise_for_status()
        request_id = submit.json()["request_id"]

        # Poll: correct endpoint is /requests/{request_id} (not /async/{request_id})
        for _ in range(120):  # max ~10 min (120 × 5s)
            await asyncio.sleep(5)
            poll = await client.get(
                f"{UPSTAGE_BASE_URL}/document-digitization/requests/{request_id}",
                headers=headers,
                timeout=30.0,
            )
            poll.raise_for_status()
            result = poll.json()
            status = result.get("status")

            if status == "failed":
                raise RuntimeError(f"Document Parse async job failed: {result}")

            if status == "completed":
                # Download each batch and merge elements + content.markdown
                # (download_url expires in 15 min)
                all_elements: list[dict] = []
                md_parts: list[str] = []
                text_parts: list[str] = []
                for batch in result.get("batches", []):
                    dl_url = batch.get("download_url")
                    if not dl_url:
                        continue
                    dl = await client.get(dl_url, timeout=60.0)
                    dl.raise_for_status()
                    batch_data = dl.json()
                    all_elements.extend(batch_data.get("elements", []))
                    bc = batch_data.get("content") or {}
                    if bc.get("markdown"):
                        md_parts.append(bc["markdown"])
                    if bc.get("text"):
                        text_parts.append(bc["text"])
                return {
                    "elements": all_elements,
                    "content": {
                        "markdown": "\n\n".join(md_parts),
                        "text": "\n\n".join(text_parts),
                    },
                }

    raise TimeoutError("Document Parse async job timed out after 10 minutes")


async def generate_checklist_items(
    clause_summaries: list[dict],  # [{"title": str, "requirement": str}]
    categories: list[str],
) -> list[dict]:
    """Call Solar once for the whole document and return checklist items with categories.
    Returns [{"title": str, "category": str}, ...]
    """
    summaries_text = "\n".join(
        f"[{i + 1}] {c.get('title') or '(제목없음)'}: {(c.get('requirement') or '')[:400]}"
        for i, c in enumerate(clause_summaries[:40])
    )
    categories_text = "\n".join(f"- {cat}" for cat in categories)

    prompt = f"""당신은 정보보호 인증 전문가입니다.
다음은 업로드된 보안 문서의 조항 목록입니다. 이 문서를 기반으로 조직이 수행해야 할 체크리스트 항목을 20개 이내로 생성해주세요.

조항 목록:
{summaries_text}

분류 가능한 카테고리 (반드시 아래 중 하나 선택):
{categories_text}

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{{"items": [{{"title": "항목명", "category": "카테고리명"}}, ...]}}"""

    raw = await chat_completion([{"role": "user", "content": prompt}])
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group())
        return data.get("items", [])
    except json.JSONDecodeError:
        return []
