from __future__ import annotations

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class RetrievalPlan(BaseModel):
    semantic_query: str
    keywords: list[str] = []
    exact_identifiers: list[str] = []
    error_codes: list[str] = []


class CandidateDTO(BaseModel):
    known_error_id: UUID
    article_version_id: UUID
    title: str
    exact_score: float = 0
    lexical_score: float = 0
    vector_score: float = 0
    final_score: float = 0
    rank: int = 0


class EvaluationResult(BaseModel):
    recommendation: Literal["USE_EXISTING", "UPDATE_EXISTING", "CREATE_NEW"]
    selected_known_error_id: UUID | None = None
    selected_article_version_id: UUID | None = None
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    evidence_ids: list[UUID] = []


class KnowledgeProposal(BaseModel):
    action: Literal["CREATE", "UPDATE"]
    target_known_error_id: UUID | None = None
    title: str
    problem: str
    root_cause: str
    solution: str
    evidence_ids: list[UUID] = []


class EvidenceReference(BaseModel):
    known_error_id: UUID
    article_version_id: UUID
    title: str


class GroundedAnswer(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference]
