"""Provider error taxonomy used by application exception handling."""


class LLMProviderError(RuntimeError):
    """Base class for normalized provider failures."""


class LLMUnavailableError(LLMProviderError):
    """The configured model runtime could not be reached."""


class LLMResponseError(LLMProviderError):
    """The runtime returned an invalid or failed response."""
