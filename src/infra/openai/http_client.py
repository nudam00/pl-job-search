"""Interact with the OpenAI API using HTTP requests."""

from typing import Any
from urllib.parse import urlparse

import httpx

REQUEST_TIMEOUT_SECONDS = 120


class OpenAIHttpError(RuntimeError):
    """Error raised when an HTTP error occurs while interacting with the OpenAI API."""

    def __init__(
        self,
        status: int,
        code: str,
        error_type: str | None,
        message: str,
        retry_after: str | None,
    ) -> None:
        """Initialize the OpenAIHttpError with details about the HTTP error.

        Args:
            status (int): The HTTP status code.
            code (str): The error code.
            error_type (str | None): The type of the error.
            message (str): The error message.
            retry_after (str | None): The time to wait before retrying the request.

        """
        self.status = status
        self.code = code
        self.error_type = error_type
        self.retry_after = retry_after
        super().__init__(
            f"HTTP {status} ({code})" + (f": {message[:200]}" if message else "")
        )


class OpenAIHttpClient:
    """HTTP client for interacting with the OpenAI API."""

    def __init__(self, api_key: str) -> None:
        """Initialize the OpenAIHttpClient with an API key.

        Args:
            api_key (str): The API key for authenticating with the OpenAI API.

        """
        self.api_key = api_key

    def post(
        self, path: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        """Send a POST request to the OpenAI API.

        Args:
            path (str): The API endpoint path.
            payload (dict): The request payload.
            timeout (float): The request timeout in seconds.

        Returns:
            dict: The JSON response from the API.

        Raises:
            OpenAIHttpError: If there is an HTTP error while interacting with the OpenAI API.
            RuntimeError: If the request cannot reach the OpenAI API.
            TypeError: If the response is not a valid JSON object.

        """
        url = f"https://api.openai.com{path}"
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.openai.com":
            msg = f"Unexpected OpenAI URL: {url}"
            raise ValueError(msg)
        try:
            response = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except (ValueError, TypeError):
                body = {}
            error = body.get("error") if isinstance(body, dict) else None
            if not isinstance(error, dict):
                error = {}
            raise OpenAIHttpError(
                exc.response.status_code,
                error.get("code") or "unknown",
                error.get("type"),
                str(error.get("message") or ""),
                exc.response.headers.get("Retry-After"),
            ) from exc
        except httpx.RequestError as exc:
            msg = f"OpenAI request failed: {exc}"
            raise RuntimeError(msg) from exc
        if not isinstance(data, dict):
            msg = "Invalid OpenAI JSON response"
            raise TypeError(msg)
        return data
