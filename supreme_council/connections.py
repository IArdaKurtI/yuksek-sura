"""Persistent API connections with Windows user-bound secret protection."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .provider import ModelEndpoint

ConnectionRole = Literal["strategist", "critic", "synthesizer"]

PROVIDERS: tuple[str, ...] = (
    "OpenAI",
    "Gemini",
    "Anthropic",
    "OpenRouter",
    "Groq",
    "Mistral",
    "DeepSeek",
    "Custom",
)

_PROVIDER_PREFIXES = {
    "openai": "openai",
    "gemini": "gemini",
    "anthropic": "anthropic",
    "openrouter": "openrouter",
    "groq": "groq",
    "mistral": "mistral",
    "deepseek": "deepseek",
}


class ConnectionError(RuntimeError):
    """Base error for connection validation or persistence."""


class SecretStorageError(ConnectionError):
    """Raised when an API key cannot be protected or recovered."""


class SecretCodec(Protocol):
    def protect(self, value: str) -> str: ...

    def unprotect(self, value: str) -> str: ...


class APIConnection(BaseModel):
    """A user-managed, role-aware provider connection."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    name: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=180)
    api_key: SecretStr = Field(min_length=1)
    api_base: str | None = Field(default=None, max_length=500)
    roles: tuple[ConnectionRole, ...] = Field(min_length=1)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("roles")
    @classmethod
    def unique_roles(
        cls, value: tuple[ConnectionRole, ...]
    ) -> tuple[ConnectionRole, ...]:
        return tuple(dict.fromkeys(value))

    @field_validator("api_base")
    @classmethod
    def empty_api_base_is_none(cls, value: str | None) -> str | None:
        return value or None

    @property
    def litellm_model(self) -> str:
        if "/" in self.model or self.provider.casefold() == "custom":
            return self.model
        prefix = _PROVIDER_PREFIXES.get(self.provider.casefold())
        return f"{prefix}/{self.model}" if prefix else self.model

    def to_endpoint(self) -> ModelEndpoint:
        return ModelEndpoint(
            model=self.litellm_model,
            label=self.name,
            api_key=self.api_key.get_secret_value(),
            api_base=self.api_base,
        )


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsDPAPISecretCodec:
    """Encrypt secrets for the current Windows user using DPAPI."""

    _DESCRIPTION = "Yuksek Sura API connection"
    _ENTROPY = b"yuksek-sura:connections:v1"
    _UI_FORBIDDEN = 0x01

    def __init__(self) -> None:
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            raise SecretStorageError("Secure API storage requires Windows DPAPI")

        self._crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        return blob, buffer

    def protect(self, value: str) -> str:
        raw_blob, raw_buffer = self._blob(value.encode("utf-8"))
        entropy_blob, entropy_buffer = self._blob(self._ENTROPY)
        protected_blob = _DataBlob()
        _ = raw_buffer, entropy_buffer  # Keep buffers alive for the native call.

        success = self._crypt32.CryptProtectData(
            ctypes.byref(raw_blob),
            self._DESCRIPTION,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(protected_blob),
        )
        if not success:
            raise SecretStorageError(
                f"API key could not be protected (Windows error {ctypes.get_last_error()})"
            )
        try:
            protected = ctypes.string_at(
                protected_blob.pbData, protected_blob.cbData
            )
            return base64.b64encode(protected).decode("ascii")
        finally:
            self._kernel32.LocalFree(protected_blob.pbData)

    def unprotect(self, value: str) -> str:
        try:
            protected = base64.b64decode(value.encode("ascii"), validate=True)
        except (ValueError, UnicodeError) as exc:
            raise SecretStorageError("Stored API key is corrupted") from exc

        protected_blob, protected_buffer = self._blob(protected)
        entropy_blob, entropy_buffer = self._blob(self._ENTROPY)
        raw_blob = _DataBlob()
        _ = protected_buffer, entropy_buffer

        success = self._crypt32.CryptUnprotectData(
            ctypes.byref(protected_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            self._UI_FORBIDDEN,
            ctypes.byref(raw_blob),
        )
        if not success:
            raise SecretStorageError(
                "API key could not be unlocked for the current Windows user"
            )
        try:
            return ctypes.string_at(raw_blob.pbData, raw_blob.cbData).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretStorageError("Stored API key is corrupted") from exc
        finally:
            self._kernel32.LocalFree(raw_blob.pbData)


def default_connection_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "YuksekSura" / "connections.json"


class ConnectionStore:
    """Atomic connection persistence with a last-known-good backup."""

    VERSION = 1

    def __init__(
        self,
        path: Path | None = None,
        *,
        codec: SecretCodec | None = None,
    ) -> None:
        self.path = path or default_connection_path()
        self.backup_path = self.path.with_suffix(".backup.json")
        self.codec = codec or WindowsDPAPISecretCodec()
        self.last_error: str | None = None

    def load(self) -> list[APIConnection]:
        self.last_error = None
        candidates = [self.path, self.backup_path]
        errors: list[str] = []

        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                connections = self._load_file(candidate)
                if candidate == self.backup_path:
                    self.last_error = "Ana bağlantı dosyası bozuk; yedek kopya açıldı."
                return connections
            except Exception as exc:  # noqa: BLE001 - corrupted storage boundary
                errors.append(f"{candidate.name}: {type(exc).__name__}: {exc}")

        if errors:
            self.last_error = "Bağlantılar açılamadı. " + " | ".join(errors)
        return []

    def save(self, connections: list[APIConnection]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "connections": [self._encode(connection) for connection in connections],
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        temp_path = self.path.with_suffix(f".{uuid4().hex}.tmp")

        try:
            temp_path.write_text(serialized, encoding="utf-8")
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
            os.replace(temp_path, self.path)
        except OSError as exc:
            raise ConnectionError(f"Bağlantılar kaydedilemedi: {exc}") from exc
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_file(self, path: Path) -> list[APIConnection]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != self.VERSION:
            raise ConnectionError("Unsupported connection file version")
        items = payload.get("connections")
        if not isinstance(items, list):
            raise ConnectionError("Connection list is missing")

        connections: list[APIConnection] = []
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise ConnectionError("Invalid connection record")
            encrypted_key = item.get("encrypted_api_key")
            if not isinstance(encrypted_key, str):
                raise ConnectionError("Encrypted API key is missing")
            public_data = {
                key: value for key, value in item.items() if key != "encrypted_api_key"
            }
            connection = APIConnection(
                **public_data,
                api_key=self.codec.unprotect(encrypted_key),
            )
            if connection.id in seen_ids:
                raise ConnectionError("Duplicate connection identifier")
            seen_ids.add(connection.id)
            connections.append(connection)
        return connections

    def _encode(self, connection: APIConnection) -> dict[str, object]:
        public_data = connection.model_dump(
            mode="json",
            exclude={"api_key"},
        )
        public_data["encrypted_api_key"] = self.codec.protect(
            connection.api_key.get_secret_value()
        )
        return public_data


def endpoints_by_role(
    connections: list[APIConnection],
) -> dict[ConnectionRole, tuple[ModelEndpoint, ...]]:
    grouped: dict[ConnectionRole, list[ModelEndpoint]] = {
        "strategist": [],
        "critic": [],
        "synthesizer": [],
    }
    for connection in connections:
        if not connection.enabled:
            continue
        endpoint = connection.to_endpoint()
        for role in connection.roles:
            grouped[role].append(endpoint)
    return {role: tuple(endpoints) for role, endpoints in grouped.items()}
