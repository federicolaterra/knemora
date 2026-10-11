"""Typed, client-safe ingestion failures."""


class IngestionRequestError(Exception):
    """A rejected ingestion request safe to surface as a problem response."""

    status_code = 400
    error_type = "urn:knemora:error:invalid-upload"
    title = "Invalid upload"


class UnsupportedFileError(IngestionRequestError):
    status_code = 415
    error_type = "urn:knemora:error:unsupported-file"
    title = "Unsupported file"


class UploadTooLargeError(IngestionRequestError):
    status_code = 413
    error_type = "urn:knemora:error:upload-too-large"
    title = "Upload too large"


class DocumentNotFoundError(IngestionRequestError):
    status_code = 404
    error_type = "urn:knemora:error:document-not-found"
    title = "Document not found"


class IngestionJobNotFoundError(IngestionRequestError):
    status_code = 404
    error_type = "urn:knemora:error:ingestion-job-not-found"
    title = "Ingestion job not found"


class IngestionRetryConflictError(IngestionRequestError):
    status_code = 409
    error_type = "urn:knemora:error:ingestion-retry-conflict"
    title = "Ingestion job cannot be retried"


class SourceIntegrityError(IngestionRequestError):
    status_code = 409
    error_type = "urn:knemora:error:source-integrity"
    title = "Immutable source integrity check failed"


class ParserFailure(Exception):
    """A parser rejected or could not safely interpret source bytes."""
