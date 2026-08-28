"""Black-and-white resilient desktop interface for Yüksek Şura."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import os
import queue
import threading
import tkinter as tk
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

from pydantic import ValidationError

from .config import CouncilSettings
from .connections import (
    APIConnection,
    PROVIDERS,
    ConnectionError,
    ConnectionStore,
    endpoints_by_role,
)
from .council import QualityGateFailed
from .factory import build_council_from_endpoints
from .provider import ProviderError

logger = logging.getLogger(__name__)

BG = "#050505"
PANEL = "#0b0b0b"
FIELD = "#111111"
FG = "#f5f5f5"
MUTED = "#c6c6c6"
BORDER = "#555555"
GOOD = "#e8e8e8"
BAD = "#a8a8a8"
FONT = ("Consolas", 10)
FONT_SMALL = ("Consolas", 9)
FONT_BOLD = ("Consolas", 10, "bold")
FONT_TITLE = ("Consolas", 18, "bold")
ASSET_DIR = Path(__file__).resolve().parent / "assets"
ICON_PNG = ASSET_DIR / "yuksek_sura.png"
ICON_ICO = ASSET_DIR / "yuksek_sura.ico"

ROLES = ("strategist", "critic", "synthesizer")

TEXTS: dict[str, dict[str, str]] = {
    "tr": {
        "window_title": "Yüksek Şura // API Konseyi",
        "header": "YÜKSEK ŞURA",
        "subtitle": "// ÇOKLU API KONTROL TERMİNALİ",
        "ready": "HAZIR",
        "count": "{active:02d} AKTİF / {total:02d} TOPLAM",
        "api_connections": "API BAĞLANTILARI",
        "add_api": "+ API EKLE",
        "task": "01 // GÖREV",
        "default_prompt": "Görevi buraya yazın. Şura aktif API bağlantılarıyla strateji, eleştiri ve sentez aşamalarını çalıştıracaktır.",
        "run": "▶ ŞURAYI ÇALIŞTIR",
        "stop": "■ DURDUR",
        "result": "02 // SONUÇ",
        "waiting_output": "[BEKLEMEDE]\nAktif API bağlantılarını ekleyin ve bir görev çalıştırın.",
        "no_connection": "[ BAĞLANTI YOK ]",
        "no_connection_hint": "+ API EKLE düğmesiyle ilk bağlantıyı oluşturun.",
        "active": "● AKTİF",
        "inactive_locked": "○ PASİF / KİLİTLİ",
        "roles_prefix": "ROLLER",
        "key_locked": "ANAHTAR :: •••••••••••• [KİLİTLİ]",
        "deactivate": "PASİF YAP",
        "activate": "AKTİF ET",
        "edit": "DÜZENLE",
        "delete": "SİL",
        "dialog_title": "API BAĞLANTISI",
        "dialog_heading": "+ API BAĞLANTISI",
        "connection_name": "BAĞLANTI ADI",
        "provider": "SAĞLAYICI",
        "model_id": "MODEL KİMLİĞİ",
        "model_hint": "Örn: gpt-5.4, gemini-2.5-flash veya tam LiteLLM model adı",
        "api_key": "API ANAHTARI",
        "show": "GÖSTER",
        "hide": "GİZLE",
        "api_base": "API BASE URL (OPSİYONEL)",
        "roles": "ROLLER",
        "role_strategist": "STRATEJİST",
        "role_critic": "ELEŞTİRMEN",
        "role_synthesizer": "SENTEZLEYİCİ",
        "connection_status": "BAĞLANTI DURUMU",
        "connection_enabled": "BAĞLANTI AKTİF",
        "connection_status_hint": "Roller nerede kullanılacağını; bu anahtar bağlantının hiç kullanılıp kullanılmayacağını belirler.",
        "cancel": "İPTAL",
        "save_lock": "KAYDET + KİLİTLE",
        "invalid_address": "Geçersiz adres",
        "invalid_address_body": "API Base URL http:// veya https:// ile başlamalıdır.",
        "invalid_fields": "Eksik veya geçersiz alan",
        "invalid_fields_body": "Bağlantı bilgilerini kontrol edin.",
        "busy_changes": "Çalışma sürerken bağlantılar değiştirilemez.",
        "connection_added": "API bağlantısı eklendi ve kilitlendi.",
        "connection_updated": "Bağlantı güncellendi ve yeniden kilitlendi.",
        "connection_activated": "{name} aktifleştirildi.",
        "connection_deactivated": "{name} pasifleştirildi ve kilitlendi.",
        "delete_title": "Bağlantıyı sil",
        "delete_body": "{name} kalıcı olarak silinsin mi?",
        "connection_deleted": "{name} silindi.",
        "fallback_updated": "Fallback önceliği güncellendi.",
        "save_failed": "Kayıt başarısız",
        "change_not_saved": "Bağlantı değişikliği kaydedilmedi.",
        "empty_task": "Görev boş",
        "empty_task_body": "Çalıştırılacak görevi yazın.",
        "missing_api": "Aktif API eksik",
        "missing_api_body": "Şu roller için aktif bağlantı gerekir:",
        "running_output": "[ÇALIŞIYOR]\nŞura modellerle güvenli bağlantı kuruyor...",
        "running": "ŞURA ÇALIŞIYOR",
        "stopping": "DURDURULUYOR",
        "quality_passed": "KALİTE KAPISI GEÇİLDİ",
        "no_verdict": "Şura sonuç üretmedi.",
        "quality_failed_output": "[KALİTE KAPISI: BAŞARISIZ]\nSonuç güvenlik nedeniyle yayımlanmadı.",
        "quality_failed": "KALİTE KAPISI BAŞARISIZ",
        "cancelled_output": "[DURDURULDU]\nÇalışma kullanıcı tarafından iptal edildi.",
        "cancelled": "DURDURULDU",
        "error_output": "[HATA YAKALANDI]",
        "error_status": "HATA — UYGULAMA ÇALIŞMAYA DEVAM EDİYOR",
        "provider_error": "Model bağlantıları yanıt vermedi.",
        "unexpected_error": "Beklenmeyen bir hata güvenli şekilde durduruldu ({kind}).\nBağlantıları kontrol edip yeniden deneyin. Ayrıntı uygulama günlüğüne yazıldı.",
        "ui_error_status": "ARAYÜZ HATASI YAKALANDI — DEVAM EDEBİLİRSİNİZ",
        "ui_error_title": "Hata güvenli şekilde yakalandı",
        "ui_error_body": "Arayüz işlemi tamamlanamadı ancak uygulama açık kaldı. Tekrar deneyebilirsiniz.",
        "close_title": "Çalışma sürüyor",
        "close_body": "Devam eden çağrıyı durdurup uygulamadan çıkmak istiyor musunuz?",
        "language_busy": "Dil, çalışma tamamlandıktan sonra değiştirilebilir.",
    },
    "en": {
        "window_title": "Supreme Council // API Council",
        "header": "SUPREME COUNCIL",
        "subtitle": "// MULTI-API CONTROL TERMINAL",
        "ready": "READY",
        "count": "{active:02d} ACTIVE / {total:02d} TOTAL",
        "api_connections": "API CONNECTIONS",
        "add_api": "+ ADD API",
        "task": "01 // TASK",
        "default_prompt": "Enter the task here. The council will run strategy, critique, and synthesis using active API connections.",
        "run": "▶ RUN COUNCIL",
        "stop": "■ STOP",
        "result": "02 // RESULT",
        "waiting_output": "[WAITING]\nAdd active API connections and run a task.",
        "no_connection": "[ NO CONNECTIONS ]",
        "no_connection_hint": "Create the first connection with + ADD API.",
        "active": "● ACTIVE",
        "inactive_locked": "○ INACTIVE / LOCKED",
        "roles_prefix": "ROLES",
        "key_locked": "KEY :: •••••••••••• [LOCKED]",
        "deactivate": "DEACTIVATE",
        "activate": "ACTIVATE",
        "edit": "EDIT",
        "delete": "DELETE",
        "dialog_title": "API CONNECTION",
        "dialog_heading": "+ API CONNECTION",
        "connection_name": "CONNECTION NAME",
        "provider": "PROVIDER",
        "model_id": "MODEL ID",
        "model_hint": "Example: gpt-5.4, gemini-2.5-flash, or a full LiteLLM model name",
        "api_key": "API KEY",
        "show": "SHOW",
        "hide": "HIDE",
        "api_base": "API BASE URL (OPTIONAL)",
        "roles": "ROLES",
        "role_strategist": "STRATEGIST",
        "role_critic": "CRITIC",
        "role_synthesizer": "SYNTHESIZER",
        "connection_status": "CONNECTION STATUS",
        "connection_enabled": "CONNECTION ACTIVE",
        "connection_status_hint": "Roles decide where it may be used; this switch decides whether the connection may be used at all.",
        "cancel": "CANCEL",
        "save_lock": "SAVE + LOCK",
        "invalid_address": "Invalid address",
        "invalid_address_body": "API Base URL must start with http:// or https://.",
        "invalid_fields": "Missing or invalid field",
        "invalid_fields_body": "Check the connection details.",
        "busy_changes": "Connections cannot be changed while a run is active.",
        "connection_added": "API connection added and locked.",
        "connection_updated": "Connection updated and locked again.",
        "connection_activated": "{name} activated.",
        "connection_deactivated": "{name} deactivated and locked.",
        "delete_title": "Delete connection",
        "delete_body": "Delete {name} permanently?",
        "connection_deleted": "{name} deleted.",
        "fallback_updated": "Fallback priority updated.",
        "save_failed": "Save failed",
        "change_not_saved": "Connection change was not saved.",
        "empty_task": "Task is empty",
        "empty_task_body": "Enter a task to run.",
        "missing_api": "Active API missing",
        "missing_api_body": "Active connections are required for these roles:",
        "running_output": "[RUNNING]\nThe council is connecting to models securely...",
        "running": "COUNCIL RUNNING",
        "stopping": "STOPPING",
        "quality_passed": "QUALITY GATE PASSED",
        "no_verdict": "The council produced no result.",
        "quality_failed_output": "[QUALITY GATE: FAILED]\nThe result was not released for safety.",
        "quality_failed": "QUALITY GATE FAILED",
        "cancelled_output": "[STOPPED]\nThe run was cancelled by the user.",
        "cancelled": "STOPPED",
        "error_output": "[ERROR CAUGHT]",
        "error_status": "ERROR — APPLICATION IS STILL RUNNING",
        "provider_error": "Model connections did not respond.",
        "unexpected_error": "An unexpected error was safely contained ({kind}).\nCheck the connections and try again. Details were written to the application log.",
        "ui_error_status": "UI ERROR CAUGHT — YOU CAN CONTINUE",
        "ui_error_title": "Error safely contained",
        "ui_error_body": "The interface action could not finish, but the application stayed open. You can try again.",
        "close_title": "Run in progress",
        "close_body": "Stop the active request and exit the application?",
        "language_busy": "Language can be changed after the active run finishes.",
    },
}


def _text(language: str, key: str, **values: object) -> str:
    template = TEXTS.get(language, TEXTS["tr"]).get(key, key)
    return template.format(**values)


def _load_language(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        language = payload.get("language")
        return language if language in TEXTS else "tr"
    except (OSError, ValueError, TypeError):
        return "tr"


def _save_language(path: Path, language: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(
            json.dumps({"language": language}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _enable_windows_dpi_awareness() -> None:
    """Prevent Windows from bitmap-scaling the UI, which makes text look blurry."""
    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return

    try:
        # Per-monitor v2 awareness on current Windows versions.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        ):
            return
    except (AttributeError, OSError):
        pass

    try:
        # Per-monitor awareness fallback for Windows 8.1+.
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _set_windows_app_identity() -> None:
    """Give Windows a stable taskbar identity instead of the Python icon."""
    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return
    try:
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        setter("YuksekSura.Council.Desktop")
    except (AttributeError, OSError, TypeError):
        logger.warning("Windows application identity could not be set", exc_info=True)


def _configure_tk_scaling(root: tk.Tk) -> None:
    """Match Tk point sizes to the real DPI reported by the active monitor."""
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", max(1.0, dpi / 72.0))
    except (tk.TclError, TypeError, ValueError):
        logger.warning("Tk DPI scaling could not be configured", exc_info=True)


def _button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    width: int | None = None,
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        width=width,
        bg=BG,
        fg=FG,
        activebackground=FG,
        activeforeground=BG,
        disabledforeground=MUTED,
        relief="solid",
        borderwidth=1,
        highlightthickness=0,
        padx=8,
        pady=5,
        font=FONT_BOLD,
        cursor="hand2",
    )


def _entry(parent: tk.Misc, variable: tk.StringVar, *, show: str = "") -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=variable,
        show=show,
        bg=FIELD,
        fg=FG,
        insertbackground=FG,
        disabledbackground=PANEL,
        disabledforeground=MUTED,
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightcolor=FG,
        highlightbackground=BORDER,
        font=FONT,
    )


class CodeEditor(tk.Frame):
    """A minimal terminal-style text area with source-code line numbers."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        height: int,
        read_only: bool = False,
    ) -> None:
        super().__init__(parent, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        self.read_only = read_only
        self.line_numbers = tk.Canvas(
            self,
            width=48,
            bg=BG,
            highlightthickness=0,
        )
        self.line_numbers.pack(side="left", fill="y")
        self.scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self._scroll,
            bg=BG,
            troughcolor=PANEL,
            activebackground=FG,
        )
        self.scrollbar.pack(side="right", fill="y")
        self.text = tk.Text(
            self,
            height=height,
            wrap="word",
            undo=not read_only,
            bg=FIELD,
            fg=FG,
            insertbackground=FG,
            selectbackground=FG,
            selectforeground=BG,
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            font=FONT,
            yscrollcommand=self._on_scroll,
        )
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<KeyRelease>", self._schedule_redraw, add="+")
        self.text.bind("<Configure>", self._schedule_redraw, add="+")
        self.text.bind("<MouseWheel>", self._schedule_redraw, add="+")
        if read_only:
            self.text.configure(state="disabled")
        self.after_idle(self._redraw)

    def _scroll(self, *args: str) -> None:
        self.text.yview(*args)
        self._redraw()

    def _on_scroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        self._redraw()

    def _schedule_redraw(self, _event: tk.Event[Any] | None = None) -> None:
        self.after_idle(self._redraw)

    def _redraw(self) -> None:
        if not self.winfo_exists():
            return
        self.line_numbers.delete("all")
        index = self.text.index("@0,0")
        while True:
            line_info = self.text.dlineinfo(index)
            if line_info is None:
                break
            y = line_info[1]
            line = index.split(".")[0]
            self.line_numbers.create_text(
                38,
                y,
                anchor="ne",
                text=line,
                fill=MUTED,
                font=FONT_SMALL,
            )
            index = self.text.index(f"{index}+1line")

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        previous_state = str(self.text.cget("state"))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        if previous_state == "disabled" or self.read_only:
            self.text.configure(state="disabled")
        self._redraw()


class ConnectionDialog(tk.Toplevel):
    """Modal editor; secrets are visible only while explicitly editing."""

    def __init__(
        self,
        parent: tk.Misc,
        connection: APIConnection | None = None,
        *,
        language: str = "tr",
    ) -> None:
        super().__init__(parent)
        self.language = language
        self.configure(bg=BG)
        self.title(self._t("dialog_title"))
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: APIConnection | None = None
        self.connection = connection

        self.name_var = tk.StringVar(value=connection.name if connection else "")
        self.provider_var = tk.StringVar(
            value=connection.provider if connection else PROVIDERS[0]
        )
        self.model_var = tk.StringVar(value=connection.model if connection else "")
        self.key_var = tk.StringVar(
            value=connection.api_key.get_secret_value() if connection else ""
        )
        self.base_var = tk.StringVar(value=connection.api_base or "" if connection else "")
        current_roles = set(connection.roles if connection else ROLES)
        self.role_vars = {
            role: tk.BooleanVar(value=role in current_roles) for role in ROLES
        }
        self.show_key_var = tk.BooleanVar(value=False)

        body = tk.Frame(self, bg=BG, padx=22, pady=18)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text=self._t("dialog_heading"),
            bg=BG,
            fg=FG,
            font=FONT_TITLE,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 18))

        self._labeled_entry(body, 1, self._t("connection_name"), self.name_var)

        tk.Label(body, text=self._t("provider"), bg=BG, fg=MUTED, font=FONT_SMALL).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(10, 3)
        )
        provider_menu = tk.OptionMenu(body, self.provider_var, *PROVIDERS)
        provider_menu.configure(
            bg=FIELD,
            fg=FG,
            activebackground=FG,
            activeforeground=BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="solid",
            borderwidth=1,
            font=FONT,
            width=48,
        )
        provider_menu["menu"].configure(bg=FIELD, fg=FG, font=FONT)
        provider_menu.grid(row=4, column=0, columnspan=3, sticky="ew")

        self._labeled_entry(body, 5, self._t("model_id"), self.model_var)
        tk.Label(
            body,
            text=self._t("model_hint"),
            bg=BG,
            fg=MUTED,
            font=FONT_SMALL,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(3, 0))

        tk.Label(body, text=self._t("api_key"), bg=BG, fg=MUTED, font=FONT_SMALL).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(10, 3)
        )
        self.key_entry = _entry(body, self.key_var, show="•")
        self.key_entry.grid(row=9, column=0, columnspan=2, sticky="ew")
        self.key_toggle_button = _button(
            body, self._t("show"), self._toggle_key, width=8
        )
        self.key_toggle_button.grid(
            row=9, column=2, sticky="e", padx=(8, 0)
        )

        self._labeled_entry(body, 10, self._t("api_base"), self.base_var)

        tk.Label(body, text=self._t("roles"), bg=BG, fg=MUTED, font=FONT_SMALL).grid(
            row=12, column=0, columnspan=3, sticky="w", pady=(10, 3)
        )
        roles_frame = tk.Frame(body, bg=BG)
        roles_frame.grid(row=13, column=0, columnspan=3, sticky="w")
        for role in ROLES:
            tk.Checkbutton(
                roles_frame,
                text=self._t(f"role_{role}"),
                variable=self.role_vars[role],
                bg=BG,
                fg=FG,
                selectcolor=FIELD,
                activebackground=BG,
                activeforeground=FG,
                font=FONT_SMALL,
            ).pack(side="left", padx=(0, 12))

        actions = tk.Frame(body, bg=BG)
        actions.grid(row=14, column=0, columnspan=3, sticky="e", pady=(20, 0))
        _button(actions, self._t("cancel"), self.destroy, width=10).pack(
            side="left", padx=(0, 8)
        )
        _button(actions, self._t("save_lock"), self._save, width=18).pack(
            side="left"
        )

        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after_idle(self._center)

    def _t(self, key: str, **values: object) -> str:
        return _text(self.language, key, **values)

    @staticmethod
    def _labeled_entry(
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        tk.Label(parent, text=label, bg=BG, fg=MUTED, font=FONT_SMALL).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 3)
        )
        entry = _entry(parent, variable)
        entry.grid(row=row + 1, column=0, columnspan=3, sticky="ew")

    def _toggle_key(self) -> None:
        visible = not self.show_key_var.get()
        self.show_key_var.set(visible)
        self.key_entry.configure(show="" if visible else "•")
        self.key_toggle_button.configure(
            text=self._t("hide" if visible else "show")
        )

    def _save(self) -> None:
        roles = tuple(role for role, selected in self.role_vars.items() if selected.get())
        base = self.base_var.get().strip() or None
        if base and not base.lower().startswith(("http://", "https://")):
            messagebox.showerror(
                self._t("invalid_address"),
                self._t("invalid_address_body"),
                parent=self,
            )
            return

        try:
            values: dict[str, Any] = {
                "name": self.name_var.get(),
                "provider": self.provider_var.get(),
                "model": self.model_var.get(),
                "api_key": self.key_var.get(),
                "api_base": base,
                "roles": roles,
                "enabled": self.connection.enabled if self.connection else True,
            }
            if self.connection is not None:
                values["id"] = self.connection.id
                values["created_at"] = self.connection.created_at
            self.result = APIConnection(**values)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {"msg": str(exc)}
            messagebox.showerror(
                self._t("invalid_fields"),
                str(first.get("msg", self._t("invalid_fields_body"))),
                parent=self,
            )
            return
        self.destroy()

    def _center(self) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()
        self.focus_force()


class CouncilDesktopApp:
    def __init__(self, root: tk.Tk, *, store: ConnectionStore | None = None) -> None:
        self.root = root
        self.store = store or ConnectionStore()
        self.preferences_path = self.store.path.parent / "ui-settings.json"
        self.language = _load_language(self.preferences_path)
        self.connections = self.store.load()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.worker_loop: asyncio.AbstractEventLoop | None = None
        self.worker_task: asyncio.Task[Any] | None = None
        self.worker_lock = threading.Lock()
        self.cancel_requested = threading.Event()
        self.busy = False
        self.pulse_index = 0
        self.closing = False
        self.output_is_placeholder = True
        self.prompt_placeholder_active = True

        self.root.title(self._t("window_title"))
        self.root.configure(bg=BG)
        self.root.minsize(1040, 700)
        self.root.geometry("1280x820")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.report_callback_exception = self._callback_exception
        self._apply_window_icon()

        self.status_var = tk.StringVar(value=self._t("ready"))
        self.connection_count_var = tk.StringVar()
        self._build_ui()
        self._render_connections()
        self.root.focus_set()
        self.root.after(100, self._poll_events)
        if self.store.last_error:
            self._set_status(self.store.last_error)

    def _apply_window_icon(self) -> None:
        try:
            if ICON_ICO.exists():
                self.root.iconbitmap(default=str(ICON_ICO))
            if ICON_PNG.exists():
                self.window_icon = tk.PhotoImage(file=str(ICON_PNG))
                self.root.iconphoto(True, self.window_icon)
        except tk.TclError:
            logger.warning("Application icon could not be loaded", exc_info=True)

    def _t(self, key: str, **values: object) -> str:
        return _text(self.language, key, **values)

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BG, padx=18, pady=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text=self._t("header"),
            bg=BG,
            fg=FG,
            font=FONT_TITLE,
        ).pack(side="left")
        tk.Label(
            header,
            text=self._t("subtitle"),
            bg=BG,
            fg=MUTED,
            font=FONT_BOLD,
        ).pack(side="left", padx=(12, 0), pady=(6, 0))
        tk.Label(
            header,
            textvariable=self.connection_count_var,
            bg=BG,
            fg=FG,
            font=FONT_BOLD,
        ).pack(side="right", padx=(14, 0))
        language_bar = tk.Frame(header, bg=BG)
        language_bar.pack(side="right")
        for language in ("tr", "en"):
            button = _button(
                language_bar,
                language.upper(),
                lambda selected=language: self._change_language(selected),
                width=3,
            )
            if language == self.language:
                button.configure(
                    bg=FG,
                    fg=BG,
                    activebackground=FG,
                    activeforeground=BG,
                )
            button.pack(side="left", padx=(4, 0))

        divider = tk.Frame(self.root, height=1, bg=FG)
        divider.pack(fill="x", padx=18)

        split = tk.PanedWindow(
            self.root,
            orient="horizontal",
            bg=BG,
            sashwidth=4,
            sashrelief="flat",
            borderwidth=0,
        )
        split.pack(fill="both", expand=True, padx=18, pady=14)

        left = tk.Frame(split, bg=BG, width=390)
        right = tk.Frame(split, bg=BG)
        split.add(left, minsize=330, width=400)
        split.add(right, minsize=600)

        api_header = tk.Frame(left, bg=BG)
        api_header.pack(fill="x", pady=(0, 10))
        tk.Label(
            api_header,
            text=self._t("api_connections"),
            bg=BG,
            fg=FG,
            font=FONT_BOLD,
        ).pack(side="left")
        _button(api_header, self._t("add_api"), self._add_connection).pack(
            side="right"
        )

        self.api_canvas = tk.Canvas(
            left,
            bg=BG,
            highlightthickness=0,
            borderwidth=0,
        )
        api_scroll = tk.Scrollbar(left, orient="vertical", command=self.api_canvas.yview)
        self.api_canvas.configure(yscrollcommand=api_scroll.set)
        api_scroll.pack(side="right", fill="y")
        self.api_canvas.pack(side="left", fill="both", expand=True)
        self.api_list = tk.Frame(self.api_canvas, bg=BG)
        self.api_window = self.api_canvas.create_window(
            (0, 0), window=self.api_list, anchor="nw"
        )
        self.api_list.bind(
            "<Configure>",
            lambda _event: self.api_canvas.configure(
                scrollregion=self.api_canvas.bbox("all")
            ),
        )
        self.api_canvas.bind(
            "<Configure>",
            lambda event: self.api_canvas.itemconfigure(
                self.api_window, width=event.width
            ),
        )
        self.api_canvas.bind("<MouseWheel>", self._scroll_api_list)

        tk.Label(
            right,
            text=self._t("task"),
            bg=BG,
            fg=MUTED,
            font=FONT_BOLD,
        ).pack(anchor="w")
        self.prompt_editor = CodeEditor(right, height=13)
        self.prompt_editor.pack(fill="both", expand=True, pady=(5, 12))
        self._show_prompt_placeholder()

        actions = tk.Frame(right, bg=BG)
        actions.pack(fill="x", pady=(0, 12))
        self.run_button = _button(actions, self._t("run"), self._start_run)
        self.run_button.pack(side="left")
        self.stop_button = _button(actions, self._t("stop"), self._cancel_run)
        self.stop_button.configure(state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        tk.Label(
            actions,
            textvariable=self.status_var,
            bg=BG,
            fg=FG,
            font=FONT_BOLD,
        ).pack(side="right", pady=6)

        tk.Label(
            right,
            text=self._t("result"),
            bg=BG,
            fg=MUTED,
            font=FONT_BOLD,
        ).pack(anchor="w")
        self.output_editor = CodeEditor(right, height=15, read_only=True)
        self.output_editor.pack(fill="both", expand=True, pady=(5, 0))
        self.output_editor.set(self._t("waiting_output"))

    def _change_language(self, language: str) -> None:
        if language == self.language:
            return
        if self.busy:
            self._set_status(self._t("language_busy"))
            return

        prompt_was_placeholder = self.prompt_placeholder_active
        prompt = self.prompt_editor.get()
        output = self.output_editor.get()
        self.language = language
        try:
            _save_language(self.preferences_path, language)
        except OSError:
            logger.exception("UI language preference could not be saved")

        if self.output_is_placeholder:
            output = self._t("waiting_output")
        for child in self.root.winfo_children():
            child.destroy()
        self.root.title(self._t("window_title"))
        self.status_var.set(self._t("ready"))
        self._build_ui()
        if prompt_was_placeholder:
            self.root.focus_set()
        else:
            self.prompt_placeholder_active = False
            self.prompt_editor.text.configure(fg=FG)
            self.prompt_editor.set(prompt)
        self.output_editor.set(output)
        self._render_connections()

    def _show_prompt_placeholder(self) -> None:
        self.prompt_placeholder_active = True
        self.prompt_editor.text.configure(fg=MUTED)
        self.prompt_editor.set(self._t("default_prompt"))
        self.prompt_editor.text.bind(
            "<Button-1>", self._clear_prompt_placeholder, add="+"
        )
        self.prompt_editor.text.bind(
            "<FocusIn>", self._clear_prompt_placeholder, add="+"
        )

    def _clear_prompt_placeholder(self, _event: tk.Event[Any] | None = None) -> None:
        if not self.prompt_placeholder_active:
            return
        self.prompt_placeholder_active = False
        self.prompt_editor.text.configure(fg=FG)
        self.prompt_editor.set("")

    def _scroll_api_list(self, event: tk.Event[Any]) -> str:
        self.api_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _render_connections(self) -> None:
        for child in self.api_list.winfo_children():
            child.destroy()

        active_count = sum(connection.enabled for connection in self.connections)
        self.connection_count_var.set(
            self._t(
                "count",
                active=active_count,
                total=len(self.connections),
            )
        )
        if not self.connections:
            empty = tk.Frame(
                self.api_list,
                bg=PANEL,
                highlightbackground=BORDER,
                highlightthickness=1,
                padx=14,
                pady=18,
            )
            empty.pack(fill="x")
            tk.Label(
                empty,
                text=self._t("no_connection"),
                bg=PANEL,
                fg=FG,
                font=FONT_BOLD,
            ).pack(anchor="w")
            tk.Label(
                empty,
                text=self._t("no_connection_hint"),
                bg=PANEL,
                fg=MUTED,
                font=FONT_SMALL,
                wraplength=300,
                justify="left",
            ).pack(anchor="w", pady=(7, 0))
            return

        for index, connection in enumerate(self.connections):
            self._connection_card(index, connection)

    def _connection_card(self, index: int, connection: APIConnection) -> None:
        card = tk.Frame(
            self.api_list,
            bg=PANEL,
            highlightbackground=FG if connection.enabled else BORDER,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        card.pack(fill="x", pady=(0, 9), padx=(0, 4))
        top = tk.Frame(card, bg=PANEL)
        top.pack(fill="x")
        tk.Label(
            top,
            text=f"[{index + 1:02d}] {connection.name.upper()}",
            bg=PANEL,
            fg=FG if connection.enabled else MUTED,
            font=FONT_BOLD,
        ).pack(side="left")
        status_button = _button(
            top,
            self._t("active") if connection.enabled else self._t("inactive_locked"),
            lambda item_id=connection.id: self._toggle_connection(item_id),
        )
        if connection.enabled:
            status_button.configure(
                bg=FG,
                fg=BG,
                activebackground=FG,
                activeforeground=BG,
            )
        status_button.pack(side="right")

        tk.Label(
            card,
            text=f"{connection.provider} :: {connection.litellm_model}",
            bg=PANEL,
            fg=FG if connection.enabled else MUTED,
            font=FONT_SMALL,
            wraplength=330,
            justify="left",
        ).pack(anchor="w", pady=(7, 0))
        role_text = " + ".join(
            self._t(f"role_{role}") for role in connection.roles
        )
        tk.Label(
            card,
            text=f"{self._t('roles_prefix')} :: {role_text}",
            bg=PANEL,
            fg=MUTED,
            font=FONT_SMALL,
            wraplength=330,
            justify="left",
        ).pack(anchor="w", pady=(3, 0))
        tk.Label(
            card,
            text=self._t("key_locked"),
            bg=PANEL,
            fg=MUTED,
            font=FONT_SMALL,
        ).pack(anchor="w", pady=(3, 8))

        controls = tk.Frame(card, bg=PANEL)
        controls.pack(fill="x")
        _button(
            controls,
            self._t("edit"),
            lambda item_id=connection.id: self._edit_connection(item_id),
        ).pack(side="left")
        _button(
            controls,
            self._t("delete"),
            lambda item_id=connection.id: self._delete_connection(item_id),
        ).pack(side="right")
        _button(
            controls,
            "↓",
            lambda item_id=connection.id: self._move_connection(item_id, 1),
            width=2,
        ).pack(side="right", padx=(0, 4))
        _button(
            controls,
            "↑",
            lambda item_id=connection.id: self._move_connection(item_id, -1),
            width=2,
        ).pack(side="right", padx=(0, 4))

    def _add_connection(self) -> None:
        if self.busy:
            self._set_status(self._t("busy_changes"))
            return
        dialog = ConnectionDialog(self.root, language=self.language)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            updated = [*self.connections, dialog.result]
            self._commit_connections(updated, self._t("connection_added"))

    def _edit_connection(self, item_id: str) -> None:
        if self.busy:
            self._set_status(self._t("busy_changes"))
            return
        index = self._find_connection(item_id)
        if index is None:
            return
        dialog = ConnectionDialog(
            self.root,
            self.connections[index],
            language=self.language,
        )
        self.root.wait_window(dialog)
        if dialog.result is not None:
            updated = list(self.connections)
            updated[index] = dialog.result
            self._commit_connections(updated, self._t("connection_updated"))

    def _toggle_connection(self, item_id: str) -> None:
        if self.busy:
            self._set_status(self._t("busy_changes"))
            return
        index = self._find_connection(item_id)
        if index is None:
            return
        current = self.connections[index]
        updated = list(self.connections)
        updated[index] = current.model_copy(update={"enabled": not current.enabled})
        status_key = (
            "connection_activated" if not current.enabled else "connection_deactivated"
        )
        self._commit_connections(updated, self._t(status_key, name=current.name))

    def _delete_connection(self, item_id: str) -> None:
        if self.busy:
            self._set_status(self._t("busy_changes"))
            return
        index = self._find_connection(item_id)
        if index is None:
            return
        connection = self.connections[index]
        if not messagebox.askyesno(
            self._t("delete_title"),
            self._t("delete_body", name=connection.name),
            parent=self.root,
        ):
            return
        updated = [item for item in self.connections if item.id != item_id]
        self._commit_connections(
            updated,
            self._t("connection_deleted", name=connection.name),
        )

    def _move_connection(self, item_id: str, offset: int) -> None:
        if self.busy:
            return
        index = self._find_connection(item_id)
        if index is None:
            return
        target = index + offset
        if target < 0 or target >= len(self.connections):
            return
        updated = list(self.connections)
        updated[index], updated[target] = updated[target], updated[index]
        self._commit_connections(updated, self._t("fallback_updated"))

    def _find_connection(self, item_id: str) -> int | None:
        return next(
            (
                index
                for index, connection in enumerate(self.connections)
                if connection.id == item_id
            ),
            None,
        )

    def _commit_connections(
        self,
        updated: list[APIConnection],
        success_message: str,
    ) -> None:
        try:
            self.store.save(updated)
        except ConnectionError as exc:
            logger.exception("Connection persistence failed")
            messagebox.showerror(self._t("save_failed"), str(exc), parent=self.root)
            self._set_status(self._t("change_not_saved"))
            return
        self.connections = updated
        self._render_connections()
        self._set_status(success_message)

    def _start_run(self) -> None:
        if self.busy:
            return
        prompt = (
            ""
            if self.prompt_placeholder_active
            else self.prompt_editor.get().strip()
        )
        if not prompt:
            messagebox.showwarning(
                self._t("empty_task"),
                self._t("empty_task_body"),
                parent=self.root,
            )
            return

        grouped = endpoints_by_role(self.connections)
        missing = [
            self._t(f"role_{role}")
            for role, endpoints in grouped.items()
            if not endpoints
        ]
        if missing:
            messagebox.showwarning(
                self._t("missing_api"),
                self._t("missing_api_body") + "\n\n" + "\n".join(missing),
                parent=self.root,
            )
            return

        self.busy = True
        self.cancel_requested.clear()
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.output_is_placeholder = False
        self.output_editor.set(self._t("running_output"))
        self._set_status(self._t("running"))
        self._pulse_status()

        settings = CouncilSettings()
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(prompt, grouped, settings),
            name="council-worker",
            daemon=True,
        )
        self.worker.start()

    def _run_worker(
        self,
        prompt: str,
        grouped: dict[str, tuple[Any, ...]],
        settings: CouncilSettings,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self.worker_lock:
            self.worker_loop = loop
        try:
            council = build_council_from_endpoints(settings, grouped)
            task = loop.create_task(
                council.run(prompt, metadata={"source": "desktop"})
            )
            with self.worker_lock:
                self.worker_task = task
            if self.cancel_requested.is_set():
                task.cancel()
            state = loop.run_until_complete(task)
            self._save_run_state(state)
            self.events.put(("success", state))
        except asyncio.CancelledError:
            self.events.put(("cancelled", None))
        except QualityGateFailed as exc:
            self._save_run_state(exc.state)
            self.events.put(("quality_failed", exc))
        except BaseException as exc:  # noqa: BLE001 - worker crash containment
            logger.exception("Council worker failed")
            self.events.put(("error", exc))
        finally:
            pending = asyncio.all_tasks(loop)
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            with self.worker_lock:
                self.worker_loop = None
                self.worker_task = None

    def _cancel_run(self) -> None:
        if not self.busy:
            return
        self.cancel_requested.set()
        with self.worker_lock:
            loop = self.worker_loop
            task = self.worker_task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)
            self._set_status(self._t("stopping"))
            self.stop_button.configure(state="disabled")

    def _poll_events(self) -> None:
        if self.closing:
            return
        try:
            while True:
                event, payload = self.events.get_nowait()
                self._handle_worker_event(event, payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _handle_worker_event(self, event: str, payload: Any) -> None:
        self.busy = False
        self.cancel_requested.clear()
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if event == "success":
            state = payload
            verdict = state.latest_verdict
            answer = verdict.final_answer if verdict else self._t("no_verdict")
            footer = (
                f"\n\n// RUN {state.run_id}\n"
                f"// TOKENS {state.total_usage.total_tokens}"
                f" | LATENCY {state.total_latency_ms} ms"
            )
            self.output_editor.set(answer + footer)
            self._set_status(self._t("quality_passed"))
        elif event == "quality_failed":
            reasons = "\n".join(f"- {reason}" for reason in payload.reasons)
            self.output_editor.set(
                self._t("quality_failed_output") + "\n\n" + reasons
            )
            self._set_status(self._t("quality_failed"))
        elif event == "cancelled":
            self.output_editor.set(self._t("cancelled_output"))
            self._set_status(self._t("cancelled"))
        else:
            friendly = self._friendly_error(payload)
            self.output_editor.set(self._t("error_output") + "\n" + friendly)
            self._set_status(self._t("error_status"))

    def _pulse_status(self) -> None:
        if not self.busy or self.closing:
            return
        dots = "." * (self.pulse_index % 4)
        self.pulse_index += 1
        self.status_var.set(self._t("running") + dots)
        self.root.after(500, self._pulse_status)

    def _friendly_error(self, exc: BaseException) -> str:
        if isinstance(exc, ProviderError):
            return self._t("provider_error") + "\n\n" + str(exc)
        if isinstance(exc, (ConnectionError, ValueError)):
            return str(exc)
        return self._t("unexpected_error", kind=type(exc).__name__)

    def _save_run_state(self, state: Any) -> None:
        try:
            run_dir = self.store.path.parent / "runs"
            run_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            destination = run_dir / f"{timestamp}_{state.run_id}.json"
            temp = destination.with_suffix(".tmp")
            temp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temp, destination)
        except OSError:
            logger.exception("Run state could not be persisted")

    def _set_status(self, value: str) -> None:
        self.status_var.set(value.upper())

    def _callback_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        traceback_object: Any,
    ) -> None:
        logger.error(
            "UI callback failed",
            exc_info=(exc_type, exc, traceback_object),
        )
        self.busy = False
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._set_status(self._t("ui_error_status"))
        messagebox.showerror(
            self._t("ui_error_title"),
            self._t("ui_error_body"),
            parent=self.root,
        )

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
            self._t("close_title"),
            self._t("close_body"),
            parent=self.root,
        ):
            return
        self.closing = True
        if self.busy:
            self._cancel_run()
        self.root.destroy()


def _configure_logging() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    log_dir = root / "YuksekSura" / "logs"
    log_path = log_dir / "desktop.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        )
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
    except OSError:
        logging.basicConfig(level=logging.INFO)
    return log_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yüksek Şura masaüstü uygulaması")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Arayüzü açmadan masaüstü bağımlılıklarını ve güvenli depoyu denetle",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log_path = _configure_logging()
    try:
        _enable_windows_dpi_awareness()
        _set_windows_app_identity()
        store = ConnectionStore()
        if args.check:
            import tkinter  # noqa: PLC0415

            _ = tkinter.TkVersion
            if not ICON_PNG.is_file() or not ICON_ICO.is_file():
                raise FileNotFoundError("Application icon assets are missing")
            probe = "yuksek-sura-dpapi-self-test"
            if store.codec.unprotect(store.codec.protect(probe)) != probe:
                raise ConnectionError("Windows secure storage self-test failed")
            store.load()
            print(f"Masaüstü uygulaması hazır. Günlük: {log_path}")
            return

        root = tk.Tk()
        _configure_tk_scaling(root)
        CouncilDesktopApp(root, store=store)
        root.mainloop()
    except BaseException as exc:  # noqa: BLE001 - process-level crash containment
        logger.exception("Desktop startup failed")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Yüksek Şura başlatılamadı",
                f"Başlangıç hatası güvenli şekilde yakalandı.\n\n"
                f"{type(exc).__name__}: {exc}\n\nGünlük: {log_path}",
            )
            root.destroy()
        except Exception:
            pass
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
