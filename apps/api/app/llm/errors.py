"""Provider error taxonomy used by application exception handling."""


class LLMProviderError(RuntimeError):
    """Base class for normalized provider failures."""


class LLMUnavailableError(LLMProviderError):
    """The configured model runtime could not be reached."""


class LLMTimeoutError(LLMProviderError):
    """The configured model runtime exceeded the request deadline."""


class LLMTransportError(LLMProviderError):
    """The configured model runtime connection failed before a response arrived."""


class LLMResponseError(LLMProviderError):
    """The runtime returned an invalid or failed response."""


class LLMContextOverflowError(LLMProviderError):
    """The request cannot fit the configured effective context window."""


class LLMResponseTruncatedError(LLMProviderError):
    """The runtime stopped at its output limit before completing the answer."""
