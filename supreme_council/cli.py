"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import CouncilSettings
from .council import QualityGateFailed
from .factory import build_council
from .provider import ProviderError


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yüksek Şura çoklu ajan karar akışı")
    prompt_source = parser.add_mutually_exclusive_group()
    prompt_source.add_argument("prompt", nargs="?", help="Şuraya verilecek görev")
    prompt_source.add_argument(
        "--prompt-file",
        type=Path,
        help="Görevi içeren UTF-8 metin dosyası",
    )
    parser.add_argument(
        "--state-out",
        type=Path,
        help="Tüm çalışma kaydını JSON dosyasına yaz",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="API çağrısı yapmadan kurulum ve yapılandırmayı denetle",
    )
    return parser.parse_args(argv)


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = CouncilSettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    missing_keys = settings.missing_required_api_keys()
    if missing_keys:
        print("\nAPI anahtarı bulunamadı: " + ", ".join(missing_keys))
        print(
            "Proje klasöründeki .env dosyasını açıp anahtarları = işaretinden sonra yazın."
        )
        print("Dosya adının .env.txt değil, tam olarak .env olduğundan emin olun.\n")
        return 2

    if args.check:
        build_council(settings)
        print("Kurulum ve API anahtarı kontrolü başarılı.")
        print(
            "Modeller: "
            f"stratejist={settings.strategist_model}, "
            f"eleştirmen={settings.critic_model}, "
            f"sentezleyici={settings.synthesizer_model}"
        )
        return 0

    if args.prompt_file:
        try:
            prompt = args.prompt_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"Prompt dosyası okunamadı: {exc}", file=sys.stderr)
            return 2
    elif args.prompt:
        prompt = args.prompt
    else:
        try:
            prompt = input("Şura görevi: ").strip()
        except EOFError:
            prompt = ""

    if not prompt:
        print("Prompt boş olamaz.", file=sys.stderr)
        return 2

    try:
        state = await build_council(settings).run(prompt)
    except QualityGateFailed as exc:
        state = exc.state
        if args.state_out:
            args.state_out.parent.mkdir(parents=True, exist_ok=True)
            args.state_out.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nKalite kapısı başarısız: {'; '.join(exc.reasons)}", file=sys.stderr)
        return 3

    if state.latest_verdict is None:
        raise RuntimeError("Council produced no verdict")

    print(state.latest_verdict.final_answer)

    if args.state_out:
        args.state_out.parent.mkdir(parents=True, exist_ok=True)
        args.state_out.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    return 0


def main() -> None:
    try:
        exit_code = asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nİşlem kullanıcı tarafından durduruldu.", file=sys.stderr)
        exit_code = 130
    except ProviderError as exc:
        print(f"\nModel çağrısı başarısız: {exc}", file=sys.stderr)
        exit_code = 1
    except RuntimeError as exc:
        print(f"\nUygulama başlatılamadı: {exc}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
