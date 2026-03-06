from pydantic import BaseModel, Field


class IngestPathRequest(BaseModel):
    path: str = Field(..., description="Absolute or server-local path to ingest")


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


class IngestDocument(BaseModel):
    doc_id: str
    source: str
    chunks: int


class IngestDocumentsResponse(BaseModel):
    documents: list[IngestDocument]


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class Citation(BaseModel):
    source: str
    chunk_id: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    context_chunks: int


class ChatSessionResponse(BaseModel):
    session_id: str
    history: list[ChatTurn]
