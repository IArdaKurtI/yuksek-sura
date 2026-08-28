from __future__ import annotations

import base64
from pathlib import Path

from supreme_council.connections import (
    APIConnection,
    ConnectionStore,
    endpoints_by_role,
)


class FakeSecretCodec:
    def protect(self, value: str) -> str:
        return base64.b64encode(("protected:" + value).encode()).decode()

    def unprotect(self, value: str) -> str:
        decoded = base64.b64decode(value).decode()
        assert decoded.startswith("protected:")
        return decoded.removeprefix("protected:")


def connection(*, enabled: bool = True) -> APIConnection:
    return APIConnection(
        name="Primary OpenAI",
        provider="OpenAI",
        model="gpt-test",
        api_key="super-secret-key",
        roles=("strategist", "critic", "synthesizer"),
        enabled=enabled,
    )


def test_connection_store_never_writes_plaintext_key(tmp_path: Path) -> None:
    path = tmp_path / "connections.json"
    store = ConnectionStore(path, codec=FakeSecretCodec())

    store.save([connection()])
    serialized = path.read_text(encoding="utf-8")
    loaded = store.load()

    assert "super-secret-key" not in serialized
    assert loaded[0].api_key.get_secret_value() == "super-secret-key"
    assert loaded[0].litellm_model == "openai/gpt-test"


def test_disabled_connections_are_kept_but_not_routed() -> None:
    disabled = connection(enabled=False)

    grouped = endpoints_by_role([disabled])

    assert all(not endpoints for endpoints in grouped.values())
    assert disabled.api_key.get_secret_value() == "super-secret-key"


def test_connection_store_recovers_last_good_backup(tmp_path: Path) -> None:
    path = tmp_path / "connections.json"
    store = ConnectionStore(path, codec=FakeSecretCodec())
    first = connection()
    second = first.model_copy(update={"name": "Updated"})
    store.save([first])
    store.save([second])
    path.write_text("not-json", encoding="utf-8")

    recovered = store.load()

    assert recovered[0].name == "Primary OpenAI"
    assert store.last_error is not None
