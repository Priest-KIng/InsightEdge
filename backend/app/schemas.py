from pydantic import BaseModel, Field


class IngestPathRequest(BaseModel):
    path: str = Field(..., description="Absolute or server-local path to ingest")
    workspace_id: str | None = Field(default=None, min_length=1)


class IngestResponse(BaseModel):
    files_processed: int
    chunks_indexed: int
    skipped_files: int


class IngestJobCreateResponse(BaseModel):
    job_id: str
    status: str


class IngestJobStatusResponse(BaseModel):
    job_id: str
    status: str
    files_total: int
    files_processed: int
    chunks_indexed: int
    skipped_files: int
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class IngestDocument(BaseModel):
    doc_id: str
    source: str
    chunks: int


class IngestDocumentsResponse(BaseModel):
    documents: list[IngestDocument]


class WorkspaceInfo(BaseModel):
    workspace_id: str


class IngestWorkspacesResponse(BaseModel):
    workspaces: list[WorkspaceInfo]


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)
    created_at: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    system_prompt: str | None = Field(default=None, min_length=1)
    workspace_id: str | None = Field(default=None, min_length=1)
    llm_model: str | None = Field(default=None, min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class Citation(BaseModel):
    source: str
    chunk_id: str
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    snippet: str | None = None
    score: float | None = None
    retrieval_rank: int | None = None
    source_type: str | None = None
    ocr_used: bool = False
    table_used: bool = False
    block_type: str | None = None
    slide_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    context_chunks: int
    model: str | None = None
    model_source: str | None = None
    workspace_id: str | None = None
    retrieval_mode: str = "hybrid"
    retrieved_chunks: int = 0
    final_context_chunks: int = 0
    latency_ms: float | None = None
    request_id: str | None = None
    query_type: str | None = None
    complexity_score: float | None = None
    routing_rationale: str | None = None
    candidate_chunks: int = 0
    confidence: float | None = None
    groundedness: float | None = None
    refusal: bool = False
    verification_reason: str | None = None


class ChatSessionResponse(BaseModel):
    session_id: str
    history: list[ChatTurn]
