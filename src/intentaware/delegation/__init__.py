"""Background delegation providers and request formulation helpers."""

from .agent import LiveDelegator
from .config import DelegationConfig
from .demo import DemoDelegator
from .errors import (
    DelegationConfigError,
    DelegationError,
    DelegationNetworkError,
    DelegationRetrievalError,
    DelegationTimeoutError,
    DelegationVerificationError,
)
from .formulator import LlmRequestFormulator, LocalRequestFormulator
from .models import CitationClaim, DelegationDraft, RetrievedDocument, SearchHit, VerificationReport
from .retriever import MockRetriever, PublicWebRetriever, Retriever, is_public_http_url
from .verifier import CitationVerifier

__all__ = [
    "CitationClaim",
    "CitationVerifier",
    "DelegationConfig",
    "DelegationConfigError",
    "DelegationDraft",
    "DelegationError",
    "DelegationNetworkError",
    "DelegationRetrievalError",
    "DelegationTimeoutError",
    "DelegationVerificationError",
    "DemoDelegator",
    "LiveDelegator",
    "LlmRequestFormulator",
    "LocalRequestFormulator",
    "MockRetriever",
    "PublicWebRetriever",
    "RetrievedDocument",
    "Retriever",
    "SearchHit",
    "VerificationReport",
    "is_public_http_url",
]
