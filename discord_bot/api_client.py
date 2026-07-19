from __future__ import annotations

from dataclasses import dataclass

import httpx


class BackendClientError(RuntimeError):
    """Base error deliberately safe to show to a Discord user."""


class BackendUnavailableError(BackendClientError):
    pass


class BackendTimeoutError(BackendClientError):
    pass


class BackendAuthenticationError(BackendClientError):
    pass


class BackendResponseError(BackendClientError):
    pass


class BackendConversationNotFoundError(BackendResponseError):
    pass


@dataclass(frozen=True)
class LocalAgentSettings:
    base_url: str
    username: str = ""
    password: str = ""
    timeout_seconds: float = 45.0


@dataclass(frozen=True)
class BackendAnswer:
    answer: str
    conversation_id: str


class LocalAgentClient:
    """A small client for the backend; it does not implement chat or RAG logic."""

    def __init__(self, settings: LocalAgentSettings, http_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http_client or httpx.AsyncClient(base_url=settings.base_url.rstrip("/"), timeout=settings.timeout_seconds)
        self._owns_http = http_client is None
        self._jwt: str | None = None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def ask(self, question: str, *, conversation_id: str | None = None, system_prompt: str | None = None) -> str:
        return (await self.ask_with_conversation(question, conversation_id=conversation_id, system_prompt=system_prompt)).answer

    async def ask_with_conversation(self, question: str, *, conversation_id: str | None = None, system_prompt: str | None = None) -> BackendAnswer:
        if not question or not question.strip():
            raise BackendResponseError("Question cannot be empty.")
        if len(question) > 10_000:
            raise BackendResponseError("Question is too long for the backend.")
        response = await self._chat_request(question, conversation_id, system_prompt)
        if response.status_code == 401:
            self._jwt = None
            await self._refresh_jwt()
            response = await self._chat_request(question, conversation_id, system_prompt)
        if response.status_code == 401:
            raise BackendAuthenticationError("Backend authentication was rejected.")
        if response.status_code >= 500:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.")
        if response.status_code == 404 and self._error_code(response) == "CONVERSATION_NOT_FOUND":
            raise BackendConversationNotFoundError("Conversation is no longer available.")
        if response.status_code >= 400:
            raise BackendResponseError(self._error_message(response))
        try:
            payload = response.json()
            answer, returned_conversation_id = payload.get("answer"), payload.get("conversation_id")
        except ValueError as error:
            raise BackendResponseError("Backend returned an invalid response.") from error
        if not isinstance(answer, str) or not answer.strip():
            raise BackendResponseError("Backend returned no answer.")
        if not isinstance(returned_conversation_id, str) or not returned_conversation_id:
            raise BackendResponseError("Backend returned no conversation ID.")
        return BackendAnswer(answer.strip(), returned_conversation_id)

    async def _chat_request(self, question: str, conversation_id: str | None, system_prompt: str | None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._jwt}"} if self._jwt else {}
        payload: dict[str, object] = {"message": question, "stream": False}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if system_prompt:
            payload["system_prompt"] = system_prompt
        try:
            return await self._http.post("/chat", json=payload, headers=headers)
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("Backend request timed out. Please try again later.") from error
        except httpx.HTTPError as error:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.") from error

    async def _refresh_jwt(self) -> None:
        if not self.settings.username or not self.settings.password:
            raise BackendAuthenticationError("Backend requires authentication, but LOCAL_AGENT_USERNAME/PASSWORD are not configured.")
        try:
            response = await self._http.post("/api/login", json={"username": self.settings.username, "password": self.settings.password})
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("Backend login timed out. Please try again later.") from error
        except httpx.HTTPError as error:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.") from error
        if response.status_code == 404:
            raise BackendAuthenticationError("Backend returned 401 but does not expose POST /api/login.")
        if response.status_code >= 400:
            raise BackendAuthenticationError("Backend login was rejected.")
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendAuthenticationError("Backend login returned an invalid response.") from error
        token = payload.get("access_token") or payload.get("token")
        if not isinstance(token, str) or not token:
            raise BackendAuthenticationError("Backend login did not return a JWT.")
        self._jwt = token

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            message = payload.get("message")
            if isinstance(message, str) and message:
                return message[:500]
        except ValueError:
            pass
        return f"Backend request failed (HTTP {response.status_code})."

    @staticmethod
    def _error_code(response: httpx.Response) -> str | None:
        try:
            value = response.json().get("error_code")
            return value if isinstance(value, str) else None
        except ValueError:
            return None
