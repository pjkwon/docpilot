from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text

from docpilot.db import client
from docpilot.exceptions import SearchError
from docpilot.search._filter import build_sql_where
from docpilot.search.models import SearchFilter, SearchResult

EmbedFn = Callable[[str], list[float]]


def embedding_dim(embed_fn: EmbedFn | None) -> int | None:
    """embed_fn의 출력 차원. 벡터 테이블을 이 차원으로 만들어야 인덱싱·검색이 동작한다.

    내장 팩토리가 붙여둔 ``embed_fn.dim``이 있으면 호출 없이 그 값을 쓰고, 없으면(사용자 정의
    함수, API 기반 임베딩 등) 짧은 문자열로 한 번 호출해 측정한다 — API 임베딩이면 이 한 번의
    호출이 과금된다. 호출을 피하려면 함수에 ``dim`` 속성을 직접 지정하면 된다.
    embed_fn이 None이면 None.
    """
    if embed_fn is None:
        return None
    dim = getattr(embed_fn, "dim", None)
    if dim is not None:
        return int(dim)
    try:
        return len(embed_fn("dimension probe"))
    except Exception as e:
        raise SearchError("임베딩 차원 확인을 위한 embed_fn 호출 실패", detail=str(e)) from e


def search(
    query: str,
    embed_fn: EmbedFn,
    top_k: int = 10,
    filters: SearchFilter | None = None,
) -> list[SearchResult]:
    """
    Vector similarity search.

    Uses sqlite-vec (cosine distance) for SQLite,
    pgvector (cosine distance) for PostgreSQL.
    embed_fn: callable that converts text to a float vector.
    """
    if not query.strip():
        raise SearchError("Query must not be empty")

    try:
        query_vec = embed_fn(query)
    except Exception as e:
        raise SearchError("Failed to generate query embedding", detail=str(e)) from e

    if client.is_sqlite():
        return _sqlite_search(query_vec, top_k, filters)
    return _pg_search(query_vec, top_k, filters)


def _sqlite_search(
    query_vec: list[float],
    top_k: int,
    filters: SearchFilter | None,
) -> list[SearchResult]:
    try:
        import sqlite_vec
    except ImportError as e:
        raise SearchError("sqlite-vec required: pip install sqlite-vec") from e

    serialized = sqlite_vec.serialize_float32(query_vec)

    extra_where, params = build_sql_where(filters, is_sqlite=True) if filters else ("", {})

    sql = text(f"""
        SELECT v.chunk_id, c.document_id, d.source, c.content, d.metadata, v.distance
        FROM vec_chunks v
        JOIN chunks c ON c.id = v.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE v.embedding MATCH :vec AND k = :top_k{extra_where}
        ORDER BY v.distance
    """)

    with client.session() as db:
        rows = db.execute(sql, {"vec": serialized, "top_k": top_k, **params}).fetchall()

    return [
        SearchResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            source=row.source,
            content=row.content,
            score=1.0 / (1.0 + float(row.distance)),
            metadata=row.metadata,
        )
        for row in rows
    ]


def _pg_search(
    query_vec: list[float],
    top_k: int,
    filters: SearchFilter | None,
) -> list[SearchResult]:
    vec_str = f"[{','.join(str(v) for v in query_vec)}]"

    extra_where, params = build_sql_where(filters, is_sqlite=False) if filters else ("", {})
    where_clause = f"WHERE c.embedding IS NOT NULL{extra_where}"

    sql = text(f"""
        SELECT
            c.id          AS chunk_id,
            c.document_id AS document_id,
            d.source      AS source,
            c.content     AS content,
            d.metadata    AS metadata,
            1 - (c.embedding <=> :vec::vector) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where_clause}
        ORDER BY c.embedding <=> :vec::vector
        LIMIT :top_k
    """)

    with client.session() as db:
        rows = db.execute(sql, {"vec": vec_str, "top_k": top_k, **params}).fetchall()

    return [
        SearchResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            source=row.source,
            content=row.content,
            score=float(row.score),
            metadata=row.metadata,
        )
        for row in rows
    ]


def openai_embed_fn(
    api_key: str | None = None,
    model: str = "text-embedding-3-small",
) -> EmbedFn:
    """Factory that returns an OpenAI embedding function (single str or list[str])."""
    import os

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SearchError(
            "OpenAI API key not provided",
            detail="Pass api_key or set OPENAI_API_KEY env var",
        )

    try:
        from openai import OpenAI
    except ImportError as e:
        raise SearchError("openai SDK required: pip install openai") from e

    _client = OpenAI(api_key=key)

    def _embed(text):
        batch = isinstance(text, list)
        inputs = text if batch else [text]
        response = _client.embeddings.create(input=inputs, model=model)
        vecs = [r.embedding for r in response.data]
        return vecs if batch else vecs[0]

    return _embed


def voyage_embed_fn(
    api_key: str | None = None,
    model: str = "voyage-3",
) -> EmbedFn:
    """Factory that returns a Voyage AI embedding function (single str or list[str])."""
    import os

    key = api_key or os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise SearchError(
            "Voyage API key not provided",
            detail="Pass api_key or set VOYAGE_API_KEY env var",
        )

    try:
        import voyageai
    except ImportError as e:
        raise SearchError("voyageai SDK required: pip install voyageai") from e

    _client = voyageai.Client(api_key=key)

    def _embed(text):
        batch = isinstance(text, list)
        inputs = text if batch else [text]
        result = _client.embed(inputs, model=model)
        return result.embeddings if batch else result.embeddings[0]

    return _embed


def bge_embed_fn(
    model: str = "BAAI/bge-m3",
    device: str = "cpu",
    use_fp16: bool = False,
) -> EmbedFn:
    """
    Factory that returns a local BGE embedding function via FlagEmbedding.
    Model is downloaded from HuggingFace on first use and cached locally.
    Accepts a single str or list[str] for batch encoding.
    """
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as e:
        raise SearchError("FlagEmbedding required: pip install FlagEmbedding") from e

    _model = BGEM3FlagModel(model, use_fp16=use_fp16, device=device)

    def _embed(text):
        batch = isinstance(text, list)
        inputs = text if batch else [text]
        result = _model.encode(inputs)
        vecs = [v.tolist() for v in result["dense_vecs"]]
        return vecs if batch else vecs[0]

    return _embed


_DEFAULT_MODEL = "intfloat/multilingual-e5-base"
_DEFAULT_MODEL_DIM = 768


def default_embed_fn() -> "EmbedFn | None":
    """
    Returns the built-in default embedding function (768-dim, sentence-transformers).

    Uses ``intfloat/multilingual-e5-base`` — a retrieval-optimised multilingual model
    with solid Korean support. Downloaded from HuggingFace on first embed call and
    cached locally (~560 MB). Subsequent calls reuse the cached model.

    Returns ``None`` when sentence-transformers is not installed — callers should
    treat ``None`` as "no vector search available" and fall back to BM25. sentence-
    transformers + sqlite-vec are core dependencies, so this normally only happens
    if they were deliberately removed from the environment.
    """
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError:
        return None

    _state: list = []  # lazy model holder — loaded on first call, not at factory time

    def _embed(text):
        if not _state:
            _state.append(SentenceTransformer(_DEFAULT_MODEL, device="cpu"))
        model = _state[0]
        batch = isinstance(text, list)
        result = model.encode(text)
        if batch:
            return [v.tolist() for v in result]
        return result.tolist()

    # 모델은 지연 로드라 차원을 고정값으로 붙여둔다 — embedding_dim()이 모델을 로드하지 않도록
    _embed.dim = _DEFAULT_MODEL_DIM
    return _embed


def sentence_embed_fn(
    model: str = "paraphrase-multilingual-MiniLM-L12-v2",
    device: str = "cpu",
) -> EmbedFn:
    """
    Factory that returns a local sentence-transformers embedding function.
    Model is downloaded from HuggingFace on first use and cached locally.
    Accepts a single str or list[str] for batch encoding.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise SearchError("sentence-transformers required: pip install sentence-transformers") from e

    _model = SentenceTransformer(model, device=device)

    def _embed(text):
        batch = isinstance(text, list)
        result = _model.encode(text)
        if batch:
            return [v.tolist() for v in result]
        return result.tolist()

    _embed.dim = _model.get_sentence_embedding_dimension()  # 알 수 없으면 None → embedding_dim()이 측정
    return _embed
