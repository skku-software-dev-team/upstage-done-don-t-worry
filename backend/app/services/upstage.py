import asyncio
import json
import re

import httpx

from app.core.config import settings

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"

# For structured-generation task calls (generate_checklist_items,
# assign_departments_batch) — deliberately does NOT mention "no context,
# refuse" like chat_completion's default system prompts do. Those tasks
# always carry their own full instructions in the user message; this system
# prompt only needs to keep Solar from adding commentary around the JSON.
TASK_SYSTEM_PROMPT = (
    "당신은 정보보호 인증 전문가입니다. 사용자 메시지의 지시를 정확히 따르고, "
    "요청된 형식(JSON 등)으로만 응답하세요. 그 외의 설명이나 거절 문구를 덧붙이지 마세요."
)


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


async def chat_completion(messages: list[dict], context: str = "", system_prompt: str | None = None) -> str:
    """`context`/the default system prompts below are specifically for the RAG
    chatbot (rag.answer_with_rag): "no context" there means retrieval found
    nothing relevant, so Solar should refuse rather than hallucinate from
    general knowledge. Callers doing something else entirely (structured
    generation tasks like generate_checklist_items/assign_departments_batch,
    which never have "context" in this sense) MUST pass their own
    `system_prompt` — otherwise they get the "no context, refuse and ask for
    an upload" instruction by default, which has nothing to do with their
    actual task and made Solar intermittently refuse instead of returning
    the requested JSON."""
    if system_prompt is None:
        if context:
            system_prompt = (
                "당신은 정보보호 인증(ISMS-P, CSAP, ISO27001) 전문 어시스턴트입니다. "
                "반드시 아래 '참고 조항'에 있는 내용만을 근거로 답변하세요. "
                "참고 조항에 없는 인증기준, 해외 법령, 일반 상식은 언급하지 마세요. "
                "참고 조항만으로 답할 수 없으면 모른다고 답하고, 어떤 문서를 추가로 "
                "업로드하면 좋을지 안내하세요. "
                "참고 조항은 각각 [문서명 조항번호] 형식으로 시작합니다 — 답변에서 이 내용을 "
                "언급할 때마다 어느 문서의 몇 번 조항인지 그 표기를 그대로 살려서 "
                "예: '[ISMS-P 2.4.1]에 따르면...' 처럼 문장 안에 명시하세요. "
                "출처가 불명확한 조항번호만 단독으로 쓰지 마세요.\n\n"
                f"참고 조항:\n{context}"
            )
        else:
            system_prompt = (
                "당신은 정보보호 인증 전문 어시스턴트입니다. "
                "현재 업로드된 문서에서 관련 내용을 찾지 못했습니다. "
                "일반 지식으로 답변하지 말고, 관련 인증기준 문서를 먼저 업로드해달라고 안내하세요."
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


def is_transient_upstage_error(exc: BaseException) -> bool:
    """True for Upstage-call failures (parse_document, chat_completion, ...)
    worth retrying: Upstage's own async job reporting failure (observed
    cause: their internal PDF-split service hitting its own timeout —
    "context deadline exceeded" — under load), network-level timeouts, or a
    5xx from Upstage. False for 4xx errors (bad file, auth, etc.) where
    retrying the identical request won't help."""
    if isinstance(exc, (RuntimeError, TimeoutError, httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


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
    candidates_by_clause: dict[int, list[dict]] | None = None,  # {clause_index (0-based): [{"id","title","category"}, ...]}
) -> list[dict]:
    """Call Solar to turn EVERY clause into exactly one checklist item, classified
    into one of `categories`. `candidates_by_clause` carries, per clause, a short
    list of existing canonical items shortlisted by embedding similarity (see
    rag.find_similar_canonical_items) — Solar only has to confirm or reject those
    few candidates instead of scanning the entire existing checklist, which keeps
    the prompt small and the duplicate check accurate regardless of how many
    documents have been uploaded so far.

    Returns [{"title": str, "category": str, "source": int, "matches_existing_id": str | None}, ...]
    """
    if not clause_summaries:
        return []

    candidates_by_clause = candidates_by_clause or {}

    lines: list[str] = []
    for i, c in enumerate(clause_summaries):
        lines.append(f"[{i + 1}] {c.get('title') or '(제목없음)'}: {(c.get('requirement') or '')[:400]}")
        candidates = candidates_by_clause.get(i)
        if candidates:
            cand_text = ", ".join(
                f"id={cand['id']} ({cand['category']} | {cand['title']})" for cand in candidates
            )
            lines.append(f"    → 기존 유사 항목 후보: {cand_text}")
    summaries_text = "\n".join(lines)
    categories_text = "\n".join(f"- {cat}" for cat in categories)

    prompt = f"""당신은 정보보호 인증 전문가입니다.
다음은 업로드된 보안 문서의 조항 목록입니다. 각 조항 앞의 [번호]를 참고하세요.
일부 조항 아래에는 "→ 기존 유사 항목 후보"로 이미 다른 문서에서 생성된 체크리스트
항목 중 임베딩 유사도로 찾은 후보가 표시되어 있습니다.

조항 목록 (총 {len(clause_summaries)}개):
{summaries_text}

# 카테고리 (아래 목록에서만 선택)
{categories_text}

중요 규칙:
- **각 조항([번호]) 하나당 체크리스트 항목을 정확히 하나씩 생성하세요.**
  조항 개수와 결과 items 개수가 같아야 합니다. 여러 조항을 하나로 뭉치거나 요약하지 마세요.
- "기존 유사 항목 후보"가 표시된 조항은 그 후보들과 실제로 같은 요구사항인지 비교하세요.
  같으면 matches_existing_id에 그 후보의 id를 그대로 반환하고, 다르거나 후보가 없으면
  matches_existing_id를 null로 두세요.
- category 값은 위 목록의 이름을 **글자 그대로, 띄어쓰기까지 정확히** 복사하세요.
  (예: "물리보안"이 아니라 "물리적 보안", "인적보안"이 아니라 "인적 보안")
- 목록에 없는 새로운 카테고리 이름을 만들지 마세요.
- 공공기관/특정 클라우드 서비스 유형(IaaS/SaaS/DaaS) 특화 조항은 관련 카테고리가
  있다면 그쪽으로, 없다면 가장 근접한 카테고리로 분류하되 다른 일반 항목과 억지로
  섞지 마세요.
- 각 항목마다 근거가 된 조항의 [번호]를 source에 넣으세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{{"items": [{{"title": "항목명", "category": "카테고리명", "source": 조항번호, "matches_existing_id": "기존id 또는 null"}}, ...]}}"""

    raw = await chat_completion([{"role": "user", "content": prompt}], system_prompt=TASK_SYSTEM_PROMPT)
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group())
        return data.get("items", [])
    except json.JSONDecodeError:
        return []


async def assign_departments_batch(items: list[dict], departments: list[str]) -> dict[str, str]:
    """Call Solar once to classify a batch of checklist items (each
    {"id", "title", "category"}) into one of `departments`, based on title
    and category. Returns {item_id: department_name} for whatever the
    response covered (a missing id just means the caller should leave it
    unassigned, not that something is wrong).

    Deliberately per-batch rather than accepting the full item list and
    looping internally: callers should chunk (~40 items) and commit each
    batch's result before calling again — keeps every Solar call's
    prompt/response small (avoiding the timeout risk a single huge call for
    an entire org's checklist would carry) and makes a retry after a
    mid-batch failure resume instead of redoing already-assigned items."""
    if not items:
        return {}

    departments_text = "\n".join(f"- {d}" for d in departments)
    lines = [
        f"[{i + 1}] id={it['id']} | 카테고리={it['category']} | {it['title']}"
        for i, it in enumerate(items)
    ]
    items_text = "\n".join(lines)

    prompt = f"""당신은 조직 내 보안 컴플라이언스 담당 부서를 배정하는 전문가입니다.
다음은 체크리스트 항목 목록입니다. 각 항목을 실제로 수행/책임질 가능성이 가장 높은
부서 하나를 배정하세요. 카테고리 정보도 참고하되, 항목 제목이 더 구체적인 근거입니다.

항목 목록 (총 {len(items)}개):
{items_text}

# 부서 (아래 목록에서만 선택)
{departments_text}

중요 규칙:
- **각 항목([번호]) 하나당 부서를 정확히 하나씩 배정하세요.** 항목 개수와 결과
  assignments 개수가 같아야 합니다.
- department 값은 위 목록의 이름을 **글자 그대로, 띄어쓰기·특수문자까지 정확히** 복사하세요.
- 목록에 없는 새로운 부서 이름을 만들지 마세요.
- 각 결과에 해당 항목의 id를 그대로 포함하세요.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{{"assignments": [{{"id": "항목id", "department": "부서명"}}, ...]}}"""

    raw = await chat_completion([{"role": "user", "content": prompt}], system_prompt=TASK_SYSTEM_PROMPT)
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return {}

    result: dict[str, str] = {}
    for a in data.get("assignments", []):
        item_id = a.get("id")
        dept = (a.get("department") or "").strip()
        if item_id and dept:
            result[item_id] = dept
    return result
