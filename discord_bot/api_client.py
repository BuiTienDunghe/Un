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


class BackendDiscordDeliveryConflictError(BackendResponseError):
    pass


class BackendInsufficientContextError(BackendResponseError):
    """No indexed document context matched the question (HTTP 422)."""


@dataclass(frozen=True)
class LocalAgentSettings:
    base_url: str
    username: str = ""
    password: str = ""
    timeout_seconds: float = 45.0
    turn_execute_timeout_seconds: float = 180.0
    # Layer-1 shared key. Empty when the backend has no key configured, which
    # is the default single-user setup.
    api_key: str = ""


@dataclass(frozen=True)
class BackendAnswer:
    answer: str
    conversation_id: str


@dataclass(frozen=True)
class BackendRagSource:
    filename: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class BackendRagAnswer:
    answer: str
    # /rag/chat may run storeless, so unlike /chat this can be None.
    conversation_id: str | None
    sources: tuple[BackendRagSource, ...]


@dataclass(frozen=True)
class BackendDocument:
    document_id: str
    filename: str
    status: str


@dataclass(frozen=True)
class BackendDiscordSession:
    session_id: str
    backend_conversation_id: str
    created: bool
    status: str


@dataclass(frozen=True)
class BackendDiscordTurn:
    turn_id: str
    session_id: str
    sequence_number: int
    status: str
    created: bool


@dataclass(frozen=True)
class BackendDiscordTurnExecution:
    turn_id: str
    session_id: str
    sequence_number: int
    status: str
    answer: str | None
    model_used: str | None
    execution_token: str | None
    replacement_turn_id: str | None


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

    async def rag_ask(self, question: str, *, document_ids: list[str] | None = None, conversation_id: str | None = None) -> BackendRagAnswer:
        """Ask the document-QA endpoint; sources come back for the citation footer.

        Uses the long execute timeout: retrieval plus a full local-model answer
        routinely exceeds the ordinary 45s request budget.
        """
        if not question or not question.strip():
            raise BackendResponseError("Question cannot be empty.")
        if len(question) > 10_000:
            raise BackendResponseError("Question is too long for the backend.")
        payload: dict[str, object] = {"message": question, "stream": False}
        if document_ids:
            payload["document_ids"] = document_ids
        if conversation_id:
            payload["conversation_id"] = conversation_id

        async def send() -> httpx.Response:
            try:
                return await self._http.post(
                    "/rag/chat",
                    json=payload,
                    headers=self._headers(),
                    timeout=self.settings.turn_execute_timeout_seconds,
                )
            except httpx.TimeoutException as error:
                raise BackendTimeoutError("Câu hỏi tài liệu chạy quá thời gian. Hãy thử lại với câu ngắn hơn.") from error
            except httpx.HTTPError as error:
                raise BackendUnavailableError("Backend is unavailable. Please try again later.") from error

        response = await send()
        if response.status_code == 401:
            self._jwt = None
            await self._refresh_jwt()
            response = await send()
        if response.status_code == 401:
            raise BackendAuthenticationError("Backend authentication was rejected.")
        if response.status_code == 422 and self._error_code(response) == "INSUFFICIENT_CONTEXT":
            raise BackendInsufficientContextError(
                "Không tìm thấy nội dung phù hợp trong tài liệu đã index. Hãy thử tài liệu khác hoặc kiểm tra tài liệu đã index xong chưa."
            )
        if response.status_code == 503 and self._error_code(response) == "QDRANT_UNAVAILABLE":
            raise BackendUnavailableError("Kho tìm kiếm (Qdrant) đang không sẵn sàng. Hãy thử lại sau.")
        if response.status_code == 404 and self._error_code(response) == "CONVERSATION_NOT_FOUND":
            raise BackendConversationNotFoundError("Conversation is no longer available.")
        if response.status_code >= 500:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.")
        if response.status_code >= 400:
            raise BackendResponseError(self._error_message(response))
        payload_out = self._json_object(response, "rag chat")
        answer = payload_out.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise BackendResponseError("Backend returned no answer.")
        conversation = payload_out.get("conversation_id")
        raw_sources = payload_out.get("sources")
        sources: list[BackendRagSource] = []
        for item in raw_sources if isinstance(raw_sources, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
                continue
            page_start = item.get("page_start") if isinstance(item.get("page_start"), int) else None
            page_end = item.get("page_end") if isinstance(item.get("page_end"), int) else None
            sources.append(BackendRagSource(item["filename"], page_start, page_end))
        return BackendRagAnswer(
            answer.strip(),
            conversation if isinstance(conversation, str) and conversation else None,
            tuple(sources),
        )

    async def list_documents(self) -> list[BackendDocument]:
        """Indexed-document inventory for the /hoi autocomplete."""

        async def send() -> httpx.Response:
            try:
                return await self._http.get("/documents", headers=self._headers())
            except httpx.TimeoutException as error:
                raise BackendTimeoutError("Backend request timed out. Please try again later.") from error
            except httpx.HTTPError as error:
                raise BackendUnavailableError("Backend is unavailable. Please try again later.") from error

        response = await send()
        if response.status_code == 401:
            self._jwt = None
            await self._refresh_jwt()
            response = await send()
        if response.status_code >= 400:
            raise BackendResponseError(self._error_message(response))
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendResponseError("Backend returned an invalid response for documents.") from error
        documents: list[BackendDocument] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            document_id, filename = item.get("document_id"), item.get("filename")
            if isinstance(document_id, str) and isinstance(filename, str):
                documents.append(BackendDocument(document_id, filename, str(item.get("status", ""))))
        return documents

    async def resolve_discord_session(
        self,
        guild_id: str,
        channel_id: str,
        thread_id: str | None = None,
    ) -> BackendDiscordSession:
        guild_id, channel_id = guild_id.strip(), channel_id.strip()
        thread_id = thread_id.strip() if thread_id is not None else None
        if not guild_id or not channel_id or (thread_id is not None and not thread_id):
            raise BackendResponseError("Discord session identifiers cannot be empty.")
        response = await self._discord_session_request(guild_id, channel_id, thread_id)
        if response.status_code == 401:
            self._jwt = None
            await self._refresh_jwt()
            response = await self._discord_session_request(guild_id, channel_id, thread_id)
        if response.status_code == 401:
            raise BackendAuthenticationError("Backend authentication was rejected.")
        if response.status_code >= 500:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.")
        if response.status_code >= 400:
            raise BackendResponseError(self._error_message(response))
        try:
            payload = response.json()
            session_id = payload.get("session_id")
            backend_conversation_id = payload.get("backend_conversation_id")
            created = payload.get("created")
            status = payload.get("status")
        except ValueError as error:
            raise BackendResponseError("Backend returned an invalid session response.") from error
        if not isinstance(session_id, str) or not session_id:
            raise BackendResponseError("Backend returned no Discord session ID.")
        if not isinstance(backend_conversation_id, str) or not backend_conversation_id:
            raise BackendResponseError("Backend returned no conversation ID.")
        if not isinstance(created, bool) or status != "active":
            raise BackendResponseError("Backend returned an invalid Discord session state.")
        return BackendDiscordSession(session_id, backend_conversation_id, created, status)

    async def enqueue_discord_turn(
        self,
        session_id: str,
        discord_message_id: str,
        message: str,
        *,
        author_id: str,
        author_display_name: str,
        reply_to_discord_message_id: str | None = None,
        system_prompt: str | None = None,
    ) -> BackendDiscordTurn:
        payload: dict[str, object] = {
            "discord_message_id": discord_message_id,
            "message": message,
            "author_id": author_id,
            "author_display_name": author_display_name,
        }
        if reply_to_discord_message_id:
            payload["reply_to_discord_message_id"] = reply_to_discord_message_id
        if system_prompt:
            payload["system_prompt"] = system_prompt
        response = await self._authorized_post(
            f"/api/discord/sessions/{session_id}/turns",
            payload,
            "Discord turn enqueue",
        )
        body = self._json_object(response, "turn enqueue")
        turn_id, returned_session_id = body.get("turn_id"), body.get("session_id")
        sequence, status, created = body.get("sequence_number"), body.get("status"), body.get("created")
        if (
            not isinstance(turn_id, str)
            or not isinstance(returned_session_id, str)
            or not isinstance(sequence, int)
            or not isinstance(status, str)
            or not isinstance(created, bool)
        ):
            raise BackendResponseError("Backend returned an invalid Discord turn.")
        return BackendDiscordTurn(turn_id, returned_session_id, sequence, status, created)

    async def execute_discord_turn(self, turn_id: str) -> BackendDiscordTurnExecution:
        response = await self._authorized_post(
            f"/api/discord/sessions/turns/{turn_id}/execute",
            {},
            "Discord turn execution",
            timeout=self.settings.turn_execute_timeout_seconds,
        )
        body = self._json_object(response, "turn execution")
        returned_turn_id, session_id = body.get("turn_id"), body.get("session_id")
        sequence, status = body.get("sequence_number"), body.get("status")
        answer, model_used = body.get("answer"), body.get("model_used")
        token, replacement = body.get("execution_token"), body.get("replacement_turn_id")
        if (
            not isinstance(returned_turn_id, str)
            or not isinstance(session_id, str)
            or not isinstance(sequence, int)
            or not isinstance(status, str)
            or (answer is not None and not isinstance(answer, str))
            or (model_used is not None and not isinstance(model_used, str))
            or (token is not None and not isinstance(token, str))
            or (replacement is not None and not isinstance(replacement, str))
        ):
            raise BackendResponseError("Backend returned an invalid Discord turn execution.")
        return BackendDiscordTurnExecution(
            returned_turn_id,
            session_id,
            sequence,
            status,
            answer,
            model_used,
            token,
            replacement,
        )

    async def complete_discord_turn(
        self,
        turn_id: str,
        execution_token: str,
        discord_response_message_ids: list[str],
    ) -> str:
        response = await self._authorized_post(
            f"/api/discord/sessions/turns/{turn_id}/complete",
            {
                "execution_token": execution_token,
                "discord_response_message_ids": (
                    discord_response_message_ids
                ),
            },
            "Discord turn completion",
        )
        body = self._json_object(response, "turn completion")
        status = body.get("status")
        if status != "completed":
            raise BackendResponseError("Backend did not complete the Discord turn.")
        return status

    async def fail_discord_turn(
        self,
        turn_id: str,
        execution_token: str,
        error: str,
        *,
        retryable: bool,
    ) -> str:
        response = await self._authorized_post(
            f"/api/discord/sessions/turns/{turn_id}/fail",
            {
                "execution_token": execution_token,
                "error": error[:4_000],
                "retryable": retryable,
            },
            "Discord turn failure",
        )
        body = self._json_object(response, "turn failure")
        status = body.get("status")
        if status not in {"queued", "failed"}:
            raise BackendResponseError("Backend returned an invalid Discord turn failure state.")
        return status

    async def _chat_request(self, question: str, conversation_id: str | None, system_prompt: str | None) -> httpx.Response:
        headers = self._headers()
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

    async def _discord_session_request(
        self,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
    ) -> httpx.Response:
        headers = self._headers()
        payload: dict[str, object] = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "thread_id": thread_id,
        }
        try:
            return await self._http.post("/api/discord/sessions/resolve", json=payload, headers=headers)
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("Backend session resolver timed out. Please try again later.") from error
        except httpx.HTTPError as error:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.") from error

    async def _authorized_post(
        self,
        path: str,
        payload: dict[str, object],
        operation: str,
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        async def send() -> httpx.Response:
            headers = self._headers()
            try:
                request_options: dict[str, object] = {
                    "json": payload,
                    "headers": headers,
                }
                if timeout is not None:
                    request_options["timeout"] = timeout
                return await self._http.post(path, **request_options)
            except httpx.TimeoutException as error:
                raise BackendTimeoutError(f"{operation} timed out. Please try again later.") from error
            except httpx.HTTPError as error:
                raise BackendUnavailableError("Backend is unavailable. Please try again later.") from error

        response = await send()
        if response.status_code == 401:
            self._jwt = None
            await self._refresh_jwt()
            response = await send()
        if response.status_code == 401:
            raise BackendAuthenticationError("Backend authentication was rejected.")
        if response.status_code >= 500:
            raise BackendUnavailableError("Backend is unavailable. Please try again later.")
        if (
            response.status_code == 409
            and self._error_code(response) == "DISCORD_TURN_DELIVERY_CONFLICT"
        ):
            raise BackendDiscordDeliveryConflictError(
                self._error_message(response)
            )
        if response.status_code >= 400:
            raise BackendResponseError(self._error_message(response))
        return response

    @staticmethod
    def _json_object(response: httpx.Response, operation: str) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendResponseError(f"Backend returned invalid JSON for {operation}.") from error
        if not isinstance(payload, dict):
            raise BackendResponseError(f"Backend returned an invalid response for {operation}.")
        return payload

    def _headers(self) -> dict[str, str]:
        """Layer-1 API key and (future) layer-2 JWT ride on separate headers."""
        headers: dict[str, str] = {}
        if self.settings.api_key:
            headers["X-API-Key"] = self.settings.api_key
        if self._jwt:
            headers["Authorization"] = f"Bearer {self._jwt}"
        return headers

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
