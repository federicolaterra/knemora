"""Knowledge-engine failures safe to expose at the API boundary."""


class KnowledgeError(Exception):
    """Base error for deterministic knowledge operations."""


class WikiPageNotFoundError(KnowledgeError):
    """A page identifier, title, or alias did not resolve."""


class WikiConflictError(KnowledgeError):
    """A requested page or alias would be ambiguous."""


class WikiValidationError(KnowledgeError):
    """A page or Wiki failed structural validation."""


class CompilationNotFoundError(KnowledgeError):
    """A compilation job or source version was not found for the owner."""


class CompilationNotReadyError(KnowledgeError):
    """A source has not reached READY_FOR_COMPILATION."""


class InvalidKnowledgeProposalError(KnowledgeError):
    """The local model returned output outside the proposal contract."""


class SourceReferenceNotFoundError(KnowledgeError):
    """A normalized source record was absent or outside the caller's scope."""


class DatasetNotFoundError(KnowledgeError):
    """A structured source version was absent or outside the caller's scope."""


class InvalidDatasetAnalysisError(KnowledgeError):
    """A deterministic dataset analysis request is invalid."""
