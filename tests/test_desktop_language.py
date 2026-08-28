from __future__ import annotations

from pathlib import Path

from supreme_council.desktop import (
    ICON_ICO,
    ICON_PNG,
    _load_language,
    _save_language,
    _text,
)


def test_language_preference_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "ui-settings.json"

    _save_language(path, "en")

    assert _load_language(path) == "en"
    assert _text("en", "add_api") == "+ ADD API"


def test_unknown_or_corrupt_language_falls_back_to_turkish(tmp_path: Path) -> None:
    path = tmp_path / "ui-settings.json"
    path.write_text('{"language":"unknown"}', encoding="utf-8")

    assert _load_language(path) == "tr"
    assert _text("tr", "add_api") == "+ API EKLE"


def test_application_icon_assets_are_valid_container_types() -> None:
    assert ICON_PNG.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    ico_header = ICON_ICO.read_bytes()[:6]
    assert ico_header[:4] == b"\x00\x00\x01\x00"
    assert int.from_bytes(ico_header[4:6], "little") >= 8
