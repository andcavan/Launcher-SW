from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except Exception as exc:
    raise SystemExit(
        "Questa app usa 'customtkinter'. Installa con:\n\n"
        "  pip install -r requirements.txt\n\n"
        f"Dettagli import: {exc}"
    )

# Distingui tra directory dati impacchettati (read-only) e directory app (modificabile)
if getattr(sys, 'frozen', False):
    # App impacchettata: dati in _MEIPASS, CFG accanto all'exe
    DATA_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(sys.executable).parent
else:
    # Sviluppo: entrambi nella directory sorgente
    DATA_DIR = Path(__file__).resolve().parent
    APP_DIR = DATA_DIR

BASE_DIR = DATA_DIR  # Per compatibilità con codice esistente
CFG_DIR = APP_DIR / "CFG"
APP_VERSION = (DATA_DIR / "VERSION").read_text(encoding="utf-8").strip()
SETTINGS_FILE = CFG_DIR / "settings.json"

try:
    from style import ui_style as mystyle
except Exception as exc:
    raise SystemExit(
        "Impossibile caricare lo stile UI.\n"
        "Verifica la cartella: style/\n\n"
        f"Dettagli import: {exc}"
    )


@dataclass
class SetupProfile:
    name: str
    sldreg_path: str = ""
    sw_version: str = ""
    solidworks_path: str = ""
    # Legacy: usato nelle versioni precedenti per il filtro per "sezioni".
    selected_sections: list[str] = field(default_factory=list)
    cleanup_before_import: bool = True
    restore_system_options: bool = True
    restore_toolbar_layout: bool = True
    restore_toolbar_mode: str = "all"
    restore_keyboard_shortcuts: bool = True
    restore_mouse_gestures: bool = True
    restore_menu_customizations: bool = True
    restore_saved_views: bool = True


@dataclass
class RestoreOptions:
    system_options: bool = True
    toolbar_layout: bool = True
    toolbar_mode: str = "all"
    keyboard_shortcuts: bool = True
    mouse_gestures: bool = True
    menu_customizations: bool = True
    saved_views: bool = True

    def has_any_selection(self) -> bool:
        return any(
            (
                self.system_options,
                self.toolbar_layout,
                self.keyboard_shortcuts,
                self.mouse_gestures,
                self.menu_customizations,
                self.saved_views,
            )
        )


@dataclass
class LauncherSettings:
    sldreg_path: str = ""
    sw_version: str = ""
    solidworks_path: str = ""
    active_setup: str = ""
    setups: list[SetupProfile] = field(default_factory=list)


def _clean_section_list(raw_sections: object) -> list[str]:
    if not isinstance(raw_sections, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_sections:
        value = str(item or "").strip()
        if not value:
            continue
        low = value.casefold()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(value)
    return cleaned


def _normalize_toolbar_mode(value: object) -> str:
    mode = str(value or "").strip().casefold()
    if mode in ("macro", "macro_only", "macro-only", "macros", "solo_macro"):
        return "macro_only"
    return "all"


def _infer_restore_options_from_legacy_sections(legacy_sections: list[str]) -> RestoreOptions:
    if not legacy_sections:
        return RestoreOptions()

    sections_low = [section.casefold() for section in legacy_sections]

    def _contains(token: str) -> bool:
        return any(token in section for section in sections_low)

    has_menu = _contains("menu customizations")
    has_saved_views = _contains("saved views")
    has_mouse = _contains("mouse gestures")
    has_shortcuts = _contains("custom accelerators")
    has_toolbar_all = any(
        token in section
        for section in sections_low
        for token in ("toolbars", "commandmanager", "api toolbars", "viewtools")
    )
    has_toolbar_macro = _contains("user defined macros")
    has_toolbar = has_toolbar_all or has_toolbar_macro

    known_tokens = (
        "menu customizations",
        "saved views",
        "mouse gestures",
        "custom accelerators",
        "toolbars",
        "commandmanager",
        "api toolbars",
        "user defined macros",
        "viewtools",
    )
    has_system_options = any(not any(token in section for token in known_tokens) for section in sections_low)

    options = RestoreOptions(
        system_options=has_system_options,
        toolbar_layout=has_toolbar,
        toolbar_mode="macro_only" if has_toolbar_macro and not has_toolbar_all else "all",
        keyboard_shortcuts=has_shortcuts,
        mouse_gestures=has_mouse,
        menu_customizations=has_menu,
        saved_views=has_saved_views,
    )
    if options.has_any_selection():
        return options
    return RestoreOptions()


def _normalize_restore_options(options: RestoreOptions | None) -> RestoreOptions:
    if options is None:
        return RestoreOptions()
    return RestoreOptions(
        system_options=bool(options.system_options),
        toolbar_layout=bool(options.toolbar_layout),
        toolbar_mode=_normalize_toolbar_mode(options.toolbar_mode),
        keyboard_shortcuts=bool(options.keyboard_shortcuts),
        mouse_gestures=bool(options.mouse_gestures),
        menu_customizations=bool(options.menu_customizations),
        saved_views=bool(options.saved_views),
    )


def _parse_setups(raw_list: object) -> list[SetupProfile]:
    if not isinstance(raw_list, list):
        return []
    setups: list[SetupProfile] = []
    seen_names: set[str] = set()
    for row in raw_list:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        legacy_sections = _clean_section_list(row.get("selected_sections", []))
        explicit_restore_options = any(
            field_name in row
            for field_name in (
                "restore_system_options",
                "restore_toolbar_layout",
                "restore_toolbar_mode",
                "restore_keyboard_shortcuts",
                "restore_mouse_gestures",
                "restore_menu_customizations",
                "restore_saved_views",
            )
        )
        if explicit_restore_options:
            restore_options = RestoreOptions(
                system_options=bool(row.get("restore_system_options", True)),
                toolbar_layout=bool(row.get("restore_toolbar_layout", True)),
                toolbar_mode=_normalize_toolbar_mode(row.get("restore_toolbar_mode", "all")),
                keyboard_shortcuts=bool(row.get("restore_keyboard_shortcuts", True)),
                mouse_gestures=bool(row.get("restore_mouse_gestures", True)),
                menu_customizations=bool(row.get("restore_menu_customizations", True)),
                saved_views=bool(row.get("restore_saved_views", True)),
            )
        else:
            restore_options = _infer_restore_options_from_legacy_sections(legacy_sections)

        setups.append(
            SetupProfile(
                name=name,
                sldreg_path=str(row.get("sldreg_path", "")).strip(),
                sw_version=str(row.get("sw_version", "")).strip(),
                solidworks_path=str(row.get("solidworks_path", "")).strip(),
                selected_sections=legacy_sections,
                cleanup_before_import=bool(row.get("cleanup_before_import", True)),
                restore_system_options=restore_options.system_options,
                restore_toolbar_layout=restore_options.toolbar_layout,
                restore_toolbar_mode=restore_options.toolbar_mode,
                restore_keyboard_shortcuts=restore_options.keyboard_shortcuts,
                restore_mouse_gestures=restore_options.mouse_gestures,
                restore_menu_customizations=restore_options.menu_customizations,
                restore_saved_views=restore_options.saved_views,
            )
        )
    return setups


def _load_settings() -> LauncherSettings:
    CFG_DIR.mkdir(exist_ok=True)
    if not SETTINGS_FILE.is_file():
        return LauncherSettings()
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return LauncherSettings(
            sldreg_path=str(raw.get("sldreg_path", "")).strip(),
            sw_version=str(raw.get("sw_version", "")).strip(),
            solidworks_path=str(raw.get("solidworks_path", "")).strip(),
            active_setup=str(raw.get("active_setup", "")).strip(),
            setups=_parse_setups(raw.get("setups", [])),
        )
    except Exception:
        return LauncherSettings()


def _save_settings(settings: LauncherSettings) -> None:
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_path(value: str) -> Path:
    return Path(value.strip().strip('"')).expanduser()


def _find_first_sldreg() -> Path | None:
    for folder in (BASE_DIR, BASE_DIR.parent):
        for candidate in sorted(folder.glob("*.sldreg")):
            if candidate.is_file():
                return candidate
        for candidate in sorted(folder.iterdir()):
            if candidate.is_file() and candidate.suffix.lower() == ".sldreg":
                return candidate
    return None


def _detect_solidworks_exe() -> Path | None:
    from_path = shutil.which("SLDWORKS.exe")
    if from_path:
        candidate = Path(from_path)
        if candidate.is_file():
            return candidate

    roots: list[Path] = []
    for env_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            roots.append(Path(env_value))

    for root in roots:
        sw_base = root / "SOLIDWORKS Corp"
        if not sw_base.is_dir():
            continue

        direct_patterns = ("SOLIDWORKS*/SLDWORKS.exe", "*/SLDWORKS.exe")
        for pattern in direct_patterns:
            for candidate in sorted(sw_base.glob(pattern), reverse=True):
                if candidate.is_file():
                    return candidate

        for candidate in sorted(sw_base.rglob("SLDWORKS.exe"), reverse=True):
            if candidate.is_file():
                return candidate
    return None


def _get_running_solidworks_pids() -> tuple[bool, list[int], str]:
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return False, [], f"Impossibile verificare i processi SolidWorks: {exc}"

    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "").strip()
        if not error_text:
            error_text = "Impossibile verificare i processi SolidWorks."
        return False, [], error_text

    pids: list[int] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.casefold().startswith("info:"):
            continue
        try:
            row = next(csv.reader([line]))
        except Exception:
            continue
        if len(row) < 2:
            continue
        image_name = row[0].strip().strip('"').casefold()
        if image_name != "sldworks.exe":
            continue
        pid_txt = row[1].strip().strip('"')
        if pid_txt.isdigit():
            pids.append(int(pid_txt))
    return True, pids, ""


def _close_running_solidworks(timeout_seconds: float = 20.0) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["taskkill", "/IM", "SLDWORKS.exe", "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return False, f"Impossibile chiudere SolidWorks: {exc}"

    if completed.returncode != 0:
        checked, remaining, check_error = _get_running_solidworks_pids()
        if checked and not remaining:
            return True, ""
        error_text = (completed.stderr or completed.stdout or "").strip()
        if not error_text:
            error_text = "Comando taskkill terminato con errore."
        if check_error:
            error_text = f"{error_text}\n{check_error}"
        return False, error_text

    deadline = time.monotonic() + max(1.0, timeout_seconds)
    while time.monotonic() < deadline:
        checked, remaining, check_error = _get_running_solidworks_pids()
        if not checked:
            return False, check_error or "Impossibile verificare la chiusura di SolidWorks."
        if not remaining:
            return True, ""
        time.sleep(0.4)

    return False, "SolidWorks non si e chiuso entro il tempo previsto."


def _guess_sw_version(exe_path: Path) -> str:
    candidates: list[str] = [exe_path.parent.name]
    if exe_path.parent.parent != exe_path.parent:
        candidates.append(exe_path.parent.parent.name)
    for item in candidates:
        year_match = re.search(r"(20\d{2})", item)
        if year_match:
            return year_match.group(1)
        upper_item = item.upper()
        if "SOLIDWORKS" in upper_item:
            cleaned = item.replace("SOLIDWORKS", "").replace("SolidWorks", "").strip(" -_")
            if cleaned:
                return cleaned
    return ""


def _read_reg_text(file_path: Path) -> tuple[str, str]:
    payload = file_path.read_bytes()
    if payload.startswith(b"\xff\xfe") or payload.startswith(b"\xfe\xff"):
        return payload.decode("utf-16"), "utf-16"
    if payload.startswith(b"\xef\xbb\xbf"):
        return payload.decode("utf-8-sig"), "utf-8-sig"

    # REGEDIT4 e spesso ANSI/UTF-8 senza BOM: evita di tentare utf-16 per primo.
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding), encoding
        except Exception:
            continue
    return payload.decode("latin-1", errors="replace"), "latin-1"


def _section_from_registry_key(registry_key: str) -> str:
    parts = [part for part in registry_key.split("\\") if part]
    for idx, part in enumerate(parts):
        if part.upper().startswith("SOLIDWORKS "):
            if idx + 1 < len(parts):
                return parts[idx + 1]
            return "ROOT"
    return parts[-1] if parts else "ROOT"


def _parse_sldreg_blocks(file_path: Path) -> tuple[list[str], list[tuple[str, str, list[str]]], str]:
    text, encoding = _read_reg_text(file_path)
    raw_lines = text.splitlines()
    header_lines: list[str] = []
    blocks: list[tuple[str, str, list[str]]] = []
    current_lines: list[str] = []
    current_section = ""
    current_key = ""
    in_block = False

    for line in raw_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_block and current_lines:
                blocks.append((current_section, current_key, current_lines))
            key_name = stripped[1:-1].strip()
            current_section = _section_from_registry_key(key_name)
            current_key = key_name
            current_lines = [line]
            in_block = True
            continue

        if in_block:
            current_lines.append(line)
        else:
            header_lines.append(line)

    if in_block and current_lines:
        blocks.append((current_section, current_key, current_lines))

    if not header_lines:
        header_lines = ["Windows Registry Editor Version 5.00", ""]

    return header_lines, blocks, encoding


def _list_sldreg_sections(file_path: Path) -> list[str]:
    _header, blocks, _encoding = _parse_sldreg_blocks(file_path)
    sections: list[str] = []
    seen: set[str] = set()
    for section, _key, _lines in blocks:
        low = section.casefold()
        if low in seen:
            continue
        seen.add(low)
        sections.append(section)
    return sections


def _is_registry_parent(parent_key: str, child_key: str) -> bool:
    p = parent_key.rstrip("\\").casefold()
    c = child_key.rstrip("\\").casefold()
    return c == p or c.startswith(f"{p}\\")


def _minimize_cleanup_keys(raw_keys: list[str]) -> list[str]:
    unique_keys: list[str] = []
    seen: set[str] = set()
    for key in raw_keys:
        normalized = key.strip()
        if not normalized:
            continue
        low = normalized.casefold()
        if low in seen:
            continue
        seen.add(low)
        unique_keys.append(normalized)

    minimized: list[str] = []
    for key in sorted(unique_keys, key=lambda item: (item.count("\\"), len(item), item.casefold())):
        if any(_is_registry_parent(existing, key) for existing in minimized):
            continue
        minimized.append(key)
    return minimized


def _is_recent_registry_key(key_name: str) -> bool:
    low = key_name.casefold()
    tokens = (
        "recent",
        "pinned file list",
    )
    return any(token in low for token in tokens)


def _registry_key_category(key_name: str) -> str:
    low = key_name.casefold()
    if _is_recent_registry_key(key_name):
        return "recent"
    if "\\menu customizations" in low:
        return "menu_customizations"
    if "\\user interface\\saved views" in low:
        return "saved_views"
    if "\\user interface\\settings\\mouse gestures" in low:
        return "mouse_gestures"
    if "\\custom accelerators" in low:
        return "keyboard_shortcuts"
    if "\\user defined macros" in low:
        return "toolbar_macro"
    if "\\user interface\\commandmanager" in low:
        return "toolbar_layout"
    if "\\user interface\\api toolbars" in low:
        return "toolbar_layout"
    if "\\user interface\\toolbars" in low:
        return "toolbar_layout"
    if "\\user interface\\viewtools" in low:
        return "toolbar_layout"
    if "\\simplified interface\\user interface\\viewtools" in low:
        return "toolbar_layout"
    if "\\toolbars" in low:
        return "toolbar_layout"
    return "system_options"


def _should_restore_category(category: str, options: RestoreOptions) -> bool:
    if category == "recent":
        return False
    if category == "system_options":
        return options.system_options
    if category == "toolbar_macro":
        return options.toolbar_layout
    if category == "toolbar_layout":
        return options.toolbar_layout and options.toolbar_mode == "all"
    if category == "keyboard_shortcuts":
        return options.keyboard_shortcuts
    if category == "mouse_gestures":
        return options.mouse_gestures
    if category == "menu_customizations":
        return options.menu_customizations
    if category == "saved_views":
        return options.saved_views
    return False


def _collect_unsafe_cleanup_parents(excluded_keys: list[str]) -> set[str]:
    unsafe: set[str] = set()
    for key_name in excluded_keys:
        normalized = key_name.strip().rstrip("\\")
        if not normalized:
            continue
        parts = [part for part in normalized.split("\\") if part]
        if not parts:
            continue
        cursor = parts[0]
        unsafe.add(cursor.casefold())
        for part in parts[1:]:
            cursor = f"{cursor}\\{part}"
            unsafe.add(cursor.casefold())
    return unsafe


def _describe_restore_options(options: RestoreOptions) -> str:
    labels: list[str] = []
    if options.system_options:
        labels.append("opzioni sistema")
    if options.toolbar_layout:
        if options.toolbar_mode == "macro_only":
            labels.append("toolbar macro")
        else:
            labels.append("layout toolbar")
    if options.keyboard_shortcuts:
        labels.append("tasti rapidi")
    if options.mouse_gestures:
        labels.append("gesti mouse")
    if options.menu_customizations:
        labels.append("menu")
    if options.saved_views:
        labels.append("viste salvate")
    if not labels:
        return "nessuna opzione"
    return ", ".join(labels)


def _write_filtered_sldreg(
    source_file: Path,
    target_file: Path,
    restore_options: RestoreOptions,
    cleanup_before_import: bool,
) -> tuple[bool, str]:
    header_lines, blocks, encoding = _parse_sldreg_blocks(source_file)
    options = _normalize_restore_options(restore_options)
    if not options.has_any_selection():
        return False, "Seleziona almeno una voce da configurare."

    out_lines = list(header_lines)
    if out_lines and out_lines[-1] != "":
        out_lines.append("")

    selected_blocks: list[tuple[str, str, list[str], str]] = []
    excluded_keys: list[str] = []
    selected_keys: list[str] = []
    for _section, key_name, lines in blocks:
        category = _registry_key_category(key_name)
        if _should_restore_category(category, options):
            selected_blocks.append((_section, key_name, lines, category))
            selected_keys.append(key_name)
        else:
            excluded_keys.append(key_name)

    if not selected_blocks:
        return False, "Nessuna chiave del file .sldreg corrisponde alle opzioni selezionate."

    if cleanup_before_import:
        unsafe_parents = _collect_unsafe_cleanup_parents(excluded_keys)
        cleanup_candidates: list[str] = []
        seen_candidates: set[str] = set()
        for key_name in selected_keys:
            normalized = key_name.strip().rstrip("\\")
            if not normalized:
                continue
            low = normalized.casefold()
            if low in seen_candidates:
                continue
            seen_candidates.add(low)
            if low in unsafe_parents:
                continue
            cleanup_candidates.append(normalized)

        cleanup_keys = _minimize_cleanup_keys(cleanup_candidates)
        for key_name in cleanup_keys:
            out_lines.append(f"[-{key_name}]")
        if cleanup_keys:
            out_lines.append("")

    written_blocks = 0
    for _section, _key_name, lines, _category in selected_blocks:
        out_lines.extend(lines)
        if lines and lines[-1] != "":
            out_lines.append("")
        written_blocks += 1

    if written_blocks == 0:
        return False, "Nessuna chiave valida da importare nel file .sldreg."

    text = "\r\n".join(out_lines).rstrip() + "\r\n"
    target_file.write_text(text, encoding=encoding)
    return True, ""


def _import_sldreg(
    file_path: Path,
    restore_options: RestoreOptions | None = None,
    cleanup_before_import: bool = True,
) -> tuple[bool, str]:
    options = _normalize_restore_options(restore_options)
    if not options.has_any_selection():
        return False, "Seleziona almeno una voce da configurare."

    source_for_import = file_path
    temp_path: Path | None = None

    try:
        fd, temp_name = tempfile.mkstemp(prefix="swcfg_", suffix=".reg")
        os.close(fd)
        temp_path = Path(temp_name)
        ok_filter, filter_msg = _write_filtered_sldreg(
            file_path,
            temp_path,
            options,
            cleanup_before_import=cleanup_before_import,
        )
        if not ok_filter:
            return False, filter_msg
        source_for_import = temp_path

        completed = subprocess.run(
            ["reg", "import", str(source_for_import)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            mode = "pulizia + import" if cleanup_before_import else "import senza pulizia"
            scope = _describe_restore_options(options)
            return True, f"Configurazione caricata nel registro ({scope}, {mode})."
        error_text = (completed.stderr or completed.stdout or "").strip()
        if not error_text:
            error_text = "Comando reg import terminato con errore."
        return False, error_text
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


class LauncherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = _load_settings()
        self.is_dark_mode = True
        self.palette = mystyle.apply_style(dark=self.is_dark_mode)

        self.title(f"Launcher SolidWorks v{APP_VERSION}")
        self.geometry("520x520")
        self.minsize(520, 520)
        self.configure(fg_color=self.palette.bg)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.var_sldreg = ctk.StringVar(value=self.settings.sldreg_path)
        self.var_sw_version = ctk.StringVar(value=self.settings.sw_version)
        self.var_solidworks = ctk.StringVar(value=self.settings.solidworks_path)
        self.var_setup_selected = ctk.StringVar(value="")
        self.var_setup_name = ctk.StringVar(value="")
        self.var_cleanup_before_import = ctk.BooleanVar(value=True)
        self.var_restore_system_options = ctk.BooleanVar(value=True)
        self.var_restore_toolbar_layout = ctk.BooleanVar(value=True)
        self.var_restore_toolbar_mode = ctk.StringVar(value="all")
        self.var_restore_keyboard_shortcuts = ctk.BooleanVar(value=True)
        self.var_restore_mouse_gestures = ctk.BooleanVar(value=True)
        self.var_restore_menu_customizations = ctk.BooleanVar(value=True)
        self.var_restore_saved_views = ctk.BooleanVar(value=True)
        self._setup_menu_updating = False
        self._reorder_mode = False
        self._drag_setup_name: str | None = None
        self._drag_target_name: str | None = None
        self._setup_button_refs: list[tuple[str, ctk.CTkButton]] = []
        self._last_status = ""
        self._temp_notice = None

        self._bootstrap_defaults()
        self._build_ui()
        self._refresh_setups_menu(self.settings.active_setup)
        self._sync_toolbar_mode_state()

    def toggle_theme(self) -> None:
        """Cambia tra modalità dark e light."""
        self.is_dark_mode = not self.is_dark_mode
        self.palette = mystyle.apply_style(dark=self.is_dark_mode)
        self.configure(fg_color=self.palette.bg)
        # Ricostruisce l'interfaccia con la nuova palette
        for widget in self.winfo_children():
            widget.destroy()
        self._build_ui()
        self._refresh_setups_menu(self.settings.active_setup)
        self._sync_toolbar_mode_state()

    def _bootstrap_defaults(self) -> None:
        active = self._find_setup(self.settings.active_setup)
        if active:
            self._apply_setup(active)
            return

        if not self.var_sldreg.get():
            default_sldreg = _find_first_sldreg()
            if default_sldreg:
                self.var_sldreg.set(str(default_sldreg))
        if not self.var_solidworks.get():
            detected_sw = _detect_solidworks_exe()
            if detected_sw:
                self.var_solidworks.set(str(detected_sw))
        if not self.var_sw_version.get() and self.var_solidworks.get():
            version_guess = _guess_sw_version(_normalize_path(self.var_solidworks.get()))
            if version_guess:
                self.var_sw_version.set(version_guess)

    def _build_ui(self) -> None:
        shell = ctk.CTkFrame(self, fg_color=self.palette.panel, corner_radius=12)
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(3, weight=1)

        # Header con titolo e toggle tema
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 2))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=f"Launcher SolidWorks v{APP_VERSION}",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=self.palette.fg,
        ).grid(row=0, column=0, sticky="w")

        theme_button_text = "☀️ Light" if self.is_dark_mode else "🌙 Dark"
        ctk.CTkButton(
            header,
            text=theme_button_text,
            command=self.toggle_theme,
            width=100,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        ctk.CTkLabel(
            shell,
            text="Carica file .sldreg e avvia SolidWorks in un click.",
            text_color=self.palette.muted_fg,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))

        self.main_tabs = ctk.CTkTabview(shell)
        self.main_tabs.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.tab_launch = self.main_tabs.add("Avvio Rapido")
        self.tab_manage = self.main_tabs.add("Gestione Setup")

        self._build_launch_tab(self.tab_launch)
        self._build_manage_tab(self.tab_manage)
        self._set_status("Launcher pronto.")

    def _build_launch_tab(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text="Pulsanti setup salvati",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.palette.fg,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 8))
        ctk.CTkButton(
            actions,
            text="Apri Gestione Setup",
            command=self._open_manage_tab,
            fg_color=self.palette.accent,
        ).pack(side="left")
        self.btn_toggle_reorder = ctk.CTkButton(
            actions,
            text="Riordina setup (Drag&Drop)",
            command=self._toggle_reorder_mode,
            fg_color=self.palette.warn,
            width=220,
        )
        self.btn_toggle_reorder.pack(side="left", padx=(8, 0))

        self.launch_buttons_frame = ctk.CTkScrollableFrame(tab, fg_color=self.palette.panel_2)
        self.launch_buttons_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 10))

    def _build_manage_tab(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Frame scrollabile per contenere tutti i widget
        scroll_frame = ctk.CTkScrollableFrame(tab, fg_color=self.palette.panel_2)
        scroll_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        scroll_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(scroll_frame, text="Setup salvato", text_color=self.palette.fg).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 6)
        )
        self.opt_setup = ctk.CTkOptionMenu(
            scroll_frame,
            values=["Nessuno"],
            variable=self.var_setup_selected,
            command=self._on_setup_selected,
            fg_color=self.palette.accent,
            button_color=self.palette.accent,
        )
        self.opt_setup.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 6))
        setup_buttons = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        setup_buttons.grid(row=0, column=2, sticky="e", padx=(0, 12), pady=(10, 6))
        ctk.CTkButton(setup_buttons, text="Nuovo", width=92, command=self._new_setup).pack(side="left", padx=(0, 6))
        ctk.CTkButton(setup_buttons, text="Elimina", width=92, command=self._delete_setup, fg_color=self.palette.err).pack(
            side="left"
        )

        ctk.CTkLabel(scroll_frame, text="Nome setup", text_color=self.palette.fg).grid(
            row=1, column=0, sticky="w", padx=12, pady=6
        )
        self.ent_setup_name = ctk.CTkEntry(
            scroll_frame,
            textvariable=self.var_setup_name,
            fg_color=self.palette.entry_bg,
            text_color=self.palette.entry_fg,
            border_color=self.palette.border,
        )
        self.ent_setup_name.grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        ctk.CTkButton(
            scroll_frame,
            text="Salva/Aggiorna",
            width=190,
            command=self._save_setup,
            fg_color=self.palette.accent_2,
        ).grid(row=1, column=2, sticky="e", padx=(0, 12), pady=6)

        ctk.CTkLabel(scroll_frame, text="File configurazione (.sldreg)", text_color=self.palette.fg).grid(
            row=2, column=0, sticky="w", padx=12, pady=(2, 6)
        )
        self.ent_sldreg = ctk.CTkEntry(
            scroll_frame,
            textvariable=self.var_sldreg,
            fg_color=self.palette.entry_bg,
            text_color=self.palette.entry_fg,
            border_color=self.palette.border,
        )
        self.ent_sldreg.grid(row=2, column=1, sticky="ew", padx=10, pady=(2, 6))
        ctk.CTkButton(scroll_frame, text="Sfoglia", width=100, command=self._pick_sldreg, fg_color=self.palette.accent).grid(
            row=2, column=2, sticky="e", padx=(0, 12), pady=(2, 6)
        )

        ctk.CTkLabel(scroll_frame, text="Versione SolidWorks", text_color=self.palette.fg).grid(
            row=3, column=0, sticky="w", padx=12, pady=6
        )
        self.ent_sw_version = ctk.CTkEntry(
            scroll_frame,
            textvariable=self.var_sw_version,
            fg_color=self.palette.entry_bg,
            text_color=self.palette.entry_fg,
            border_color=self.palette.border,
            placeholder_text="es. 2024 SP2",
        )
        self.ent_sw_version.grid(row=3, column=1, sticky="ew", padx=10, pady=6)
        ctk.CTkButton(scroll_frame, text="Auto", width=100, command=self._autofill_sw_version, fg_color=self.palette.accent).grid(
            row=3, column=2, sticky="e", padx=(0, 12), pady=6
        )

        ctk.CTkLabel(scroll_frame, text="Eseguibile SolidWorks (SLDWORKS.exe)", text_color=self.palette.fg).grid(
            row=4, column=0, sticky="w", padx=12, pady=6
        )
        self.ent_solidworks = ctk.CTkEntry(
            scroll_frame,
            textvariable=self.var_solidworks,
            fg_color=self.palette.entry_bg,
            text_color=self.palette.entry_fg,
            border_color=self.palette.border,
        )
        self.ent_solidworks.grid(row=4, column=1, sticky="ew", padx=10, pady=6)

        btn_sw = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        btn_sw.grid(row=4, column=2, sticky="e", padx=(0, 12), pady=6)
        ctk.CTkButton(btn_sw, text="Sfoglia", width=92, command=self._pick_solidworks, fg_color=self.palette.accent).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(btn_sw, text="Rileva", width=92, command=self._detect_solidworks, fg_color=self.palette.accent_2).pack(
            side="left"
        )

        ctk.CTkLabel(scroll_frame, text="Cosa configurare (.sldreg)", text_color=self.palette.fg).grid(
            row=5, column=0, sticky="w", padx=12, pady=6
        )
        options_box = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        options_box.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(10, 12), pady=6)
        options_box.grid_columnconfigure(0, weight=1)

        ctk.CTkCheckBox(
            options_box,
            text="Opzioni del sistema",
            variable=self.var_restore_system_options,
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkCheckBox(
            options_box,
            text="Layout barra degli strumenti",
            variable=self.var_restore_toolbar_layout,
            command=self._sync_toolbar_mode_state,
        ).grid(row=1, column=0, sticky="w", pady=(0, 2))

        toolbar_mode_box = ctk.CTkFrame(options_box, fg_color="transparent")
        toolbar_mode_box.grid(row=2, column=0, sticky="w", padx=(22, 0), pady=(0, 4))
        self.rad_toolbar_all = ctk.CTkRadioButton(
            toolbar_mode_box,
            text="Tutte le barre + CommandManager",
            variable=self.var_restore_toolbar_mode,
            value="all",
        )
        self.rad_toolbar_all.pack(anchor="w")
        self.rad_toolbar_macro = ctk.CTkRadioButton(
            toolbar_mode_box,
            text="Solo barra strumenti macro",
            variable=self.var_restore_toolbar_mode,
            value="macro_only",
        )
        self.rad_toolbar_macro.pack(anchor="w", pady=(2, 0))

        ctk.CTkCheckBox(
            options_box,
            text="Tasti rapidi da tastiera",
            variable=self.var_restore_keyboard_shortcuts,
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))
        ctk.CTkCheckBox(
            options_box,
            text="Gesti del mouse",
            variable=self.var_restore_mouse_gestures,
        ).grid(row=4, column=0, sticky="w", pady=(0, 4))
        ctk.CTkCheckBox(
            options_box,
            text="Personalizzazioni menu",
            variable=self.var_restore_menu_customizations,
        ).grid(row=5, column=0, sticky="w", pady=(0, 4))
        ctk.CTkCheckBox(
            options_box,
            text="Viste salvate",
            variable=self.var_restore_saved_views,
        ).grid(row=6, column=0, sticky="w", pady=(0, 2))

        ctk.CTkCheckBox(
            scroll_frame,
            text="Pulisci chiavi selezionate prima dell'import",
            variable=self.var_cleanup_before_import,
        ).grid(row=6, column=0, columnspan=3, sticky="w", padx=12, pady=(2, 8))

        ctk.CTkButton(
            scroll_frame,
            text="Carica Configurazione + Avvia SolidWorks",
            command=self._run_launcher,
            fg_color=self.palette.accent_2,
            text_color=self.palette.fg,
            height=40,
        ).grid(row=7, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 10))
        self._sync_toolbar_mode_state()

        self.manage_log_box = ctk.CTkTextbox(
            scroll_frame,
            fg_color=self.palette.panel_2,
            text_color=self.palette.entry_fg,
            border_color=self.palette.border,
            border_width=1,
            height=150,
        )
        self.manage_log_box.grid(row=8, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        self.manage_log_box.configure(state="disabled")

    def _collect_restore_options(self) -> RestoreOptions:
        return _normalize_restore_options(
            RestoreOptions(
                system_options=bool(self.var_restore_system_options.get()),
                toolbar_layout=bool(self.var_restore_toolbar_layout.get()),
                toolbar_mode=self.var_restore_toolbar_mode.get(),
                keyboard_shortcuts=bool(self.var_restore_keyboard_shortcuts.get()),
                mouse_gestures=bool(self.var_restore_mouse_gestures.get()),
                menu_customizations=bool(self.var_restore_menu_customizations.get()),
                saved_views=bool(self.var_restore_saved_views.get()),
            )
        )

    def _apply_restore_options(self, options: RestoreOptions) -> None:
        normalized = _normalize_restore_options(options)
        self.var_restore_system_options.set(normalized.system_options)
        self.var_restore_toolbar_layout.set(normalized.toolbar_layout)
        self.var_restore_toolbar_mode.set(normalized.toolbar_mode)
        self.var_restore_keyboard_shortcuts.set(normalized.keyboard_shortcuts)
        self.var_restore_mouse_gestures.set(normalized.mouse_gestures)
        self.var_restore_menu_customizations.set(normalized.menu_customizations)
        self.var_restore_saved_views.set(normalized.saved_views)
        self._sync_toolbar_mode_state()

    def _sync_toolbar_mode_state(self) -> None:
        state = "normal" if bool(self.var_restore_toolbar_layout.get()) else "disabled"
        if hasattr(self, "rad_toolbar_all"):
            self.rad_toolbar_all.configure(state=state)
        if hasattr(self, "rad_toolbar_macro"):
            self.rad_toolbar_macro.configure(state=state)

    def _validate_restore_selection(self) -> RestoreOptions | None:
        options = self._collect_restore_options()
        if options.has_any_selection():
            return options
        messagebox.showwarning("Configurazione", "Seleziona almeno una voce da ripristinare.")
        return None

    def _open_manage_tab(self) -> None:
        self.main_tabs.set("Gestione Setup")

    def _toggle_reorder_mode(self) -> None:
        self._reorder_mode = not self._reorder_mode
        self._drag_setup_name = None
        self._drag_target_name = None
        if self._reorder_mode:
            self.btn_toggle_reorder.configure(text="Fine Riordino", fg_color=self.palette.err)
            self._set_status("Modalita riordino attiva: trascina un pulsante setup sopra un altro.")
        else:
            self.btn_toggle_reorder.configure(text="Riordina setup (Drag&Drop)", fg_color=self.palette.warn)
            self._set_status("Modalita riordino disattivata.")
        self._render_launch_buttons()

    def _move_setup_before(self, source_name: str, target_name: str) -> bool:
        if source_name.casefold() == target_name.casefold():
            return False
        source_idx = -1
        target_idx = -1
        for idx, setup in enumerate(self.settings.setups):
            low = setup.name.casefold()
            if low == source_name.casefold():
                source_idx = idx
            if low == target_name.casefold():
                target_idx = idx
        if source_idx < 0 or target_idx < 0:
            return False

        source_setup = self.settings.setups.pop(source_idx)
        if source_idx < target_idx:
            target_idx -= 1
        self.settings.setups.insert(target_idx, source_setup)
        return True

    def _drag_start(self, setup_name: str) -> None:
        if not self._reorder_mode:
            return
        self._drag_setup_name = setup_name
        self._drag_target_name = None
        self._set_status(f"Drag avviato: {setup_name}")

    def _setup_name_at_pointer(self, x_root: int, y_root: int) -> str | None:
        for setup_name, button in self._setup_button_refs:
            try:
                if not button.winfo_exists():
                    continue
                bx = button.winfo_rootx()
                by = button.winfo_rooty()
                bw = button.winfo_width()
                bh = button.winfo_height()
            except Exception:
                continue
            if bx <= x_root <= bx + bw and by <= y_root <= by + bh:
                return setup_name
        return None

    def _drag_motion(self, event) -> None:
        if not self._reorder_mode:
            return
        if not self._drag_setup_name:
            return
        target_name = self._setup_name_at_pointer(int(event.x_root), int(event.y_root))
        if not target_name:
            return
        if target_name.casefold() == self._drag_setup_name.casefold():
            return
        if not self._drag_target_name or self._drag_target_name.casefold() != target_name.casefold():
            self._drag_target_name = target_name
            self._set_status(f"Destinazione drag: {target_name}")

    def _drag_drop(self, event) -> None:
        if not self._reorder_mode:
            return
        if not self._drag_setup_name:
            return

        source_name = self._drag_setup_name
        pointer_target = self._setup_name_at_pointer(int(event.x_root), int(event.y_root))
        target_name = pointer_target or self._drag_target_name or ""
        changed = False
        if target_name:
            changed = self._move_setup_before(source_name, target_name)

        self._drag_setup_name = None
        self._drag_target_name = None

        if changed:
            active = self.settings.active_setup
            self._refresh_setups_menu(active if active else "Nessuno")
            self._persist_settings()
            self._set_status(f"Ordine setup aggiornato: {source_name} -> prima di {target_name}.")
        else:
            self._render_launch_buttons()
            self._set_status("Drag annullato: nessuna modifica ordine.")

    def _render_launch_buttons(self) -> None:
        for widget in self.launch_buttons_frame.winfo_children():
            widget.destroy()
        self._setup_button_refs = []

        if not self.settings.setups:
            ctk.CTkLabel(
                self.launch_buttons_frame,
                text="Nessun setup salvato.\nApri la tab 'Gestione Setup' per crearne uno.",
                text_color=self.palette.muted_fg,
                justify="left",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return

        columns = 2
        for col in range(columns):
            self.launch_buttons_frame.grid_columnconfigure(col, weight=1)

        active_name = self.settings.active_setup.strip().casefold()
        for idx, setup in enumerate(self.settings.setups):
            row = idx // columns
            col = idx % columns
            sw_version = setup.sw_version if setup.sw_version else "-"
            is_active = setup.name.casefold() == active_name
            is_drag_source = bool(
                self._reorder_mode and self._drag_setup_name and setup.name.casefold() == self._drag_setup_name.casefold()
            )
            is_drag_target = bool(
                self._reorder_mode and self._drag_target_name and setup.name.casefold() == self._drag_target_name.casefold()
            )
            btn_text = f"{setup.name}\nSW {sw_version}"
            if self._reorder_mode:
                btn_text = f"{setup.name}\nSW {sw_version} | DRAG"

            fg_color = self.palette.accent_2 if is_active else self.palette.accent
            if is_drag_source:
                fg_color = self.palette.warn
            elif is_drag_target:
                fg_color = self.palette.ok

            button = ctk.CTkButton(
                self.launch_buttons_frame,
                text=btn_text,
                height=60,
                width=220,
                fg_color=fg_color,
                command=(lambda name=setup.name: self._launch_saved_setup(name)) if not self._reorder_mode else None,
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            button.grid(row=row, column=col, sticky="", padx=4, pady=4)
            self._setup_button_refs.append((setup.name, button))
            if self._reorder_mode:
                button.bind("<ButtonPress-1>", lambda _e, name=setup.name: self._drag_start(name))
                button.bind("<B1-Motion>", self._drag_motion)
                button.bind("<ButtonRelease-1>", self._drag_drop)

    def _launch_saved_setup(self, setup_name: str) -> None:
        if self._reorder_mode:
            self._set_status("Disattiva prima la modalita riordino per avviare un setup.")
            return
        setup = self._find_setup(setup_name)
        if not setup:
            self._set_status("Setup rapido non trovato.", error=True)
            return
        self._apply_setup(setup)
        self.var_setup_selected.set(setup.name)
        self._refresh_setups_menu(setup.name)
        self._persist_settings()
        self._run_launcher()

    def _set_option_values(self, values: list[str]) -> None:
        self.opt_setup.configure(values=values)

    def _find_setup(self, setup_name: str) -> SetupProfile | None:
        target = setup_name.strip().casefold()
        if not target:
            return None
        for setup in self.settings.setups:
            if setup.name.casefold() == target:
                return setup
        return None

    def _refresh_setups_menu(self, selected: str = "") -> None:
        setup_names = [setup.name for setup in self.settings.setups]
        values = ["Nessuno", *setup_names]
        self._setup_menu_updating = True
        try:
            self._set_option_values(values)
            if selected and selected in values:
                to_set = selected
            elif self.var_setup_selected.get() in values:
                to_set = self.var_setup_selected.get()
            else:
                to_set = "Nessuno"
            self.var_setup_selected.set(to_set)
        finally:
            self._setup_menu_updating = False

        self.settings.active_setup = "" if to_set == "Nessuno" else to_set
        self._render_launch_buttons()

    def _apply_setup(self, setup: SetupProfile) -> None:
        self.var_setup_name.set(setup.name)
        self.var_sldreg.set(setup.sldreg_path)
        self.var_sw_version.set(setup.sw_version)
        self.var_solidworks.set(setup.solidworks_path)
        self.var_cleanup_before_import.set(bool(setup.cleanup_before_import))
        self._apply_restore_options(
            RestoreOptions(
                system_options=bool(setup.restore_system_options),
                toolbar_layout=bool(setup.restore_toolbar_layout),
                toolbar_mode=setup.restore_toolbar_mode,
                keyboard_shortcuts=bool(setup.restore_keyboard_shortcuts),
                mouse_gestures=bool(setup.restore_mouse_gestures),
                menu_customizations=bool(setup.restore_menu_customizations),
                saved_views=bool(setup.restore_saved_views),
            )
        )

    def _on_setup_selected(self, selected_name: str) -> None:
        if self._setup_menu_updating:
            return
        if selected_name == "Nessuno":
            self.settings.active_setup = ""
            self._refresh_setups_menu("Nessuno")
            self._persist_settings()
            self._set_status("Selezione setup disattivata.")
            return
        setup = self._find_setup(selected_name)
        if not setup:
            self._set_status("Setup selezionato non valido.", error=True)
            return
        self._apply_setup(setup)
        self.settings.active_setup = setup.name
        self._refresh_setups_menu(setup.name)
        self._persist_settings()
        self._set_status(f"Setup '{setup.name}' caricato.")

    def _new_setup(self) -> None:
        self.var_setup_selected.set("Nessuno")
        self.var_setup_name.set("")
        self.var_cleanup_before_import.set(True)
        self._apply_restore_options(RestoreOptions())
        self.settings.active_setup = ""
        self._refresh_setups_menu("Nessuno")
        self._persist_settings()
        self._set_status("Nuovo setup: inserisci nome e salva.")

    def _save_setup(self) -> None:
        setup_name = self.var_setup_name.get().strip()
        if not setup_name:
            messagebox.showwarning("Setup", "Inserisci il nome setup.")
            return
        sw_version = self.var_sw_version.get().strip()
        if not sw_version:
            messagebox.showwarning("Setup", "Inserisci la versione di SolidWorks.")
            return
        validated = self._validate_paths()
        if validated is None:
            return
        restore_options = self._validate_restore_selection()
        if restore_options is None:
            return

        sldreg_path, solidworks_path = validated
        cleanup_before_import = bool(self.var_cleanup_before_import.get())
        existing = self._find_setup(setup_name)
        if existing:
            existing.sldreg_path = str(sldreg_path)
            existing.sw_version = sw_version
            existing.solidworks_path = str(solidworks_path)
            existing.cleanup_before_import = cleanup_before_import
            existing.restore_system_options = restore_options.system_options
            existing.restore_toolbar_layout = restore_options.toolbar_layout
            existing.restore_toolbar_mode = restore_options.toolbar_mode
            existing.restore_keyboard_shortcuts = restore_options.keyboard_shortcuts
            existing.restore_mouse_gestures = restore_options.mouse_gestures
            existing.restore_menu_customizations = restore_options.menu_customizations
            existing.restore_saved_views = restore_options.saved_views
            action = "aggiornato"
        else:
            self.settings.setups.append(
                SetupProfile(
                    name=setup_name,
                    sldreg_path=str(sldreg_path),
                    sw_version=sw_version,
                    solidworks_path=str(solidworks_path),
                    cleanup_before_import=cleanup_before_import,
                    restore_system_options=restore_options.system_options,
                    restore_toolbar_layout=restore_options.toolbar_layout,
                    restore_toolbar_mode=restore_options.toolbar_mode,
                    restore_keyboard_shortcuts=restore_options.keyboard_shortcuts,
                    restore_mouse_gestures=restore_options.mouse_gestures,
                    restore_menu_customizations=restore_options.menu_customizations,
                    restore_saved_views=restore_options.saved_views,
                )
            )
            action = "salvato"

        self.settings.active_setup = setup_name
        self.var_setup_selected.set(setup_name)
        self._refresh_setups_menu(setup_name)
        self._persist_settings()
        self._set_status(f"Setup '{setup_name}' {action}.")

    def _delete_setup(self) -> None:
        selected_name = self.var_setup_selected.get().strip()
        if not selected_name or selected_name == "Nessuno":
            selected_name = self.var_setup_name.get().strip()
        if not selected_name:
            messagebox.showwarning("Setup", "Seleziona un setup da eliminare.")
            return
        existing = self._find_setup(selected_name)
        if not existing:
            messagebox.showwarning("Setup", "Setup non trovato.")
            return
        if not messagebox.askyesno("Setup", f"Eliminare il setup '{existing.name}'?"):
            return

        self.settings.setups = [setup for setup in self.settings.setups if setup.name.casefold() != existing.name.casefold()]
        self.settings.active_setup = ""
        self.var_setup_name.set("")
        self._refresh_setups_menu("Nessuno")
        self._persist_settings()
        self._set_status(f"Setup '{existing.name}' eliminato.")

    def _pick_sldreg(self) -> None:
        selected = filedialog.askopenfilename(
            title="Seleziona file configurazione SolidWorks",
            filetypes=[("SolidWorks Reg", "*.sldreg"), ("Tutti i file", "*.*")],
        )
        if selected:
            self.var_sldreg.set(selected)
            self._log(f"File .sldreg selezionato: {selected}")

    def _pick_solidworks(self) -> None:
        selected = filedialog.askopenfilename(
            title="Seleziona SLDWORKS.exe",
            filetypes=[("SolidWorks", "SLDWORKS.exe"), ("Eseguibili", "*.exe"), ("Tutti i file", "*.*")],
        )
        if selected:
            self.var_solidworks.set(selected)
            if not self.var_sw_version.get().strip():
                self._autofill_sw_version()
            self._log(f"Eseguibile SolidWorks selezionato: {selected}")

    def _detect_solidworks(self) -> None:
        detected = _detect_solidworks_exe()
        if not detected:
            self._set_status("SolidWorks non trovato. Seleziona il percorso manualmente.", error=True)
            return
        self.var_solidworks.set(str(detected))
        if not self.var_sw_version.get().strip():
            self._autofill_sw_version()
        self._set_status("Percorso SolidWorks rilevato.")
        self._log(f"Rilevato SLDWORKS.exe: {detected}")

    def _autofill_sw_version(self) -> None:
        solidworks_txt = self.var_solidworks.get().strip()
        if not solidworks_txt:
            messagebox.showwarning("Versione SW", "Seleziona prima il file SLDWORKS.exe.")
            return
        solidworks_path = _normalize_path(solidworks_txt)
        version_guess = _guess_sw_version(solidworks_path)
        if not version_guess:
            self._set_status("Versione non rilevata automaticamente.")
            return
        self.var_sw_version.set(version_guess)
        self._set_status(f"Versione SW rilevata: {version_guess}")

    def _set_status(self, text: str, error: bool = False) -> None:
        self._last_status = text
        if hasattr(self, "manage_log_box"):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.manage_log_box.configure(state="normal")
            self.manage_log_box.insert("end", f"[{timestamp}] {text}\n")
            self.manage_log_box.see("end")
            self.manage_log_box.configure(state="disabled")
            self.manage_log_box.configure(border_color=self.palette.err if error else self.palette.border)

    def _log(self, text: str) -> None:
        self._set_status(text)

    def _show_temporary_notice(self, title: str, text: str, duration_ms: int = 5000) -> None:
        try:
            if self._temp_notice is not None and self._temp_notice.winfo_exists():
                self._temp_notice.destroy()
        except Exception:
            pass

        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.attributes("-topmost", True)
        dlg.configure(fg_color=self.palette.panel)
        dlg.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dlg,
            text=text,
            wraplength=420,
            justify="left",
            text_color=self.palette.fg,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=16)

        dlg.update_idletasks()
        width = max(360, dlg.winfo_reqwidth())
        height = max(110, dlg.winfo_reqheight())
        x = self.winfo_rootx() + max(20, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(20, (self.winfo_height() - height) // 2)
        dlg.geometry(f"{width}x{height}+{x}+{y}")

        def _close_notice() -> None:
            try:
                if dlg.winfo_exists():
                    dlg.destroy()
            except Exception:
                pass
            if self._temp_notice is dlg:
                self._temp_notice = None

        self._temp_notice = dlg
        dlg.after(duration_ms, _close_notice)

    def _validate_paths(self) -> tuple[Path, Path] | None:
        sldreg_txt = self.var_sldreg.get().strip()
        solidworks_txt = self.var_solidworks.get().strip()

        if not sldreg_txt:
            messagebox.showwarning("Launcher", "Seleziona il file .sldreg.")
            return None
        if not solidworks_txt:
            messagebox.showwarning("Launcher", "Seleziona il file SLDWORKS.exe.")
            return None

        sldreg_path = _normalize_path(sldreg_txt)
        solidworks_path = _normalize_path(solidworks_txt)

        if not sldreg_path.is_file():
            messagebox.showerror("Launcher", f"File .sldreg non trovato:\n{sldreg_path}")
            return None
        if sldreg_path.suffix.lower() != ".sldreg":
            messagebox.showerror("Launcher", "Il file configurazione deve avere estensione .sldreg.")
            return None
        if not solidworks_path.is_file():
            messagebox.showerror("Launcher", f"Eseguibile non trovato:\n{solidworks_path}")
            return None
        if solidworks_path.name.lower() != "sldworks.exe":
            messagebox.showerror("Launcher", "Seleziona il file SLDWORKS.exe.")
            return None

        return sldreg_path, solidworks_path

    def _run_launcher(self) -> None:
        if os.name != "nt":
            messagebox.showerror("Launcher", "Questa app funziona solo su Windows.")
            return

        if not self.var_sw_version.get().strip():
            messagebox.showwarning("Launcher", "Inserisci la versione di SolidWorks.")
            return

        validated = self._validate_paths()
        if validated is None:
            return
        restore_options = self._validate_restore_selection()
        if restore_options is None:
            return

        sldreg_path, solidworks_path = validated
        checked, running_pids, check_msg = _get_running_solidworks_pids()
        if not checked:
            self._set_status("Impossibile verificare sessioni SolidWorks aperte.", error=True)
            messagebox.showerror("Launcher", check_msg)
            return

        if running_pids:
            running_count = len(running_pids)
            label = "sessione" if running_count == 1 else "sessioni"
            confirm = messagebox.askyesno(
                "SolidWorks gia aperto",
                (
                    f"Sono state rilevate {running_count} {label} di SolidWorks aperte.\n\n"
                    "Se continui, SolidWorks verra chiuso e perderai eventuale lavoro non salvato.\n\n"
                    "Vuoi chiudere le sessioni aperte e continuare?"
                ),
            )
            if not confirm:
                self._set_status("Avvio annullato: SolidWorks gia aperto.")
                return

            self._set_status("Chiusura sessioni SolidWorks in corso...")
            closed, close_msg = _close_running_solidworks()
            if not closed:
                self._set_status("Errore chiusura SolidWorks.", error=True)
                messagebox.showerror("Chiusura SolidWorks", close_msg)
                return

            self._set_status("Sessioni SolidWorks chiuse.")

        cleanup_before_import = bool(self.var_cleanup_before_import.get())
        self._persist_settings()

        self._set_status("Import configurazione in corso...")
        imported, import_msg = _import_sldreg(
            sldreg_path,
            restore_options=restore_options,
            cleanup_before_import=cleanup_before_import,
        )
        if not imported:
            self._set_status("Errore caricamento configurazione.", error=True)
            messagebox.showerror("Import .sldreg", import_msg)
            return

        self._set_status(import_msg)
        try:
            subprocess.Popen([str(solidworks_path)], cwd=str(solidworks_path.parent))
        except Exception as exc:
            self._set_status("Errore avvio SolidWorks.", error=True)
            messagebox.showerror("Avvio SolidWorks", str(exc))
            return

        self._set_status("SolidWorks avviato correttamente.")
        self._show_temporary_notice("Launcher", "Configurazione caricata e SolidWorks avviato.", duration_ms=5000)

    def _persist_settings(self) -> None:
        self.settings.sldreg_path = self.var_sldreg.get().strip()
        self.settings.sw_version = self.var_sw_version.get().strip()
        self.settings.solidworks_path = self.var_solidworks.get().strip()
        selected = self.var_setup_selected.get().strip()
        self.settings.active_setup = "" if selected == "Nessuno" else selected
        _save_settings(self.settings)

    def on_close(self) -> None:
        self._persist_settings()
        self.destroy()


def main() -> None:
    LauncherApp().mainloop()


if __name__ == "__main__":
    main()
