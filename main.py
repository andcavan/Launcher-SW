from __future__ import annotations

import json
import os
import tempfile
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


if getattr(sys, "frozen", False):
    DATA_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    APP_DIR = Path(sys.executable).parent
else:
    DATA_DIR = Path(__file__).resolve().parent
    APP_DIR = DATA_DIR

BASE_DIR = DATA_DIR
CFG_DIR = APP_DIR / "CFG"
SETTINGS_FILE = CFG_DIR / "settings.json"
_SETUP_BOOL_FIELDS = (
    "cleanup_before_import",
    "restore_system_options",
    "restore_toolbar_layout",
    "restore_keyboard_shortcuts",
    "restore_mouse_gestures",
    "restore_menu_customizations",
    "restore_saved_views",
)

try:
    APP_VERSION = (DATA_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.9.14"
except Exception:
    APP_VERSION = "0.9.14"


DARK_THEME = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #1e1e2e;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 6px 12px;
    min-width: 80px;
}
QPushButton:hover { background-color: #45475a; border-color: #89b4fa; }
QPushButton:pressed { background-color: #585b70; }
QLineEdit, QComboBox, QTextEdit {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}
QTabWidget::pane {
    border: 1px solid #313244;
}
QTabBar::tab {
    background: #181825;
    color: #cdd6f4;
    padding: 6px 10px;
    border: 1px solid #313244;
}
QTabBar::tab:selected {
    background: #313244;
}
QPushButton#cfgLaunchButton {
    min-height: 56px;
    min-width: 112px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#cfgLaunchButtonLast {
    min-height: 56px;
    min-width: 112px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 700;
    background-color: #16a34a;
    border-color: #15803d;
    color: #ecfdf5;
}
QPushButton#cfgLaunchButtonLast:hover {
    background-color: #15803d;
    border-color: #166534;
}
QPushButton#cfgLaunchButtonLast:pressed {
    background-color: #166534;
}
"""


@dataclass
class SetupProfile:
    name: str
    sldreg_path: str = ""
    sw_version: str = ""
    solidworks_path: str = ""
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
class LauncherSettings:
    sldreg_path: str = ""
    sw_version: str = ""
    solidworks_path: str = ""
    active_setup: str = ""
    setups: list[SetupProfile] = field(default_factory=list)


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


def _setup_row_needs_migration(row: dict[str, object]) -> bool:
    for field_name in _SETUP_BOOL_FIELDS:
        if field_name not in row:
            return True
    toolbar_mode = _normalize_toolbar_mode(row.get("restore_toolbar_mode", "all"))
    if toolbar_mode not in {"all", "macro_only"}:
        return True
    return False


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


def _read_reg_text(file_path: Path) -> tuple[str, str]:
    payload = file_path.read_bytes()
    if payload.startswith(b"\xff\xfe") or payload.startswith(b"\xfe\xff"):
        return payload.decode("utf-16"), "utf-16"
    if payload.startswith(b"\xef\xbb\xbf"):
        return payload.decode("utf-8-sig"), "utf-8-sig"

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
    for section, key_name, lines in blocks:
        category = _registry_key_category(key_name)
        if _should_restore_category(category, options):
            selected_blocks.append((section, key_name, lines, category))
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


def _is_solidworks_running() -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}".lower()
    return "sldworks.exe" in output


def _kill_solidworks_processes() -> tuple[bool, str]:
    completed = subprocess.run(
        ["taskkill", "/IM", "SLDWORKS.exe", "/F", "/T"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return True, ""
    msg = (completed.stderr or completed.stdout or "Impossibile chiudere le sessioni SolidWorks.").strip()
    return False, msg


def _parse_setups(raw_list: object) -> list[SetupProfile]:
    if not isinstance(raw_list, list):
        return []
    parsed: list[SetupProfile] = []
    seen: set[str] = set()
    for row in raw_list:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
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

        parsed.append(
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
    return parsed


def _load_settings() -> LauncherSettings:
    CFG_DIR.mkdir(exist_ok=True)
    if not SETTINGS_FILE.is_file():
        return LauncherSettings()
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        raw_setups = raw.get("setups", [])
        settings = LauncherSettings(
            sldreg_path=str(raw.get("sldreg_path", "")).strip(),
            sw_version=str(raw.get("sw_version", "")).strip(),
            solidworks_path=str(raw.get("solidworks_path", "")).strip(),
            active_setup=str(raw.get("active_setup", "")).strip(),
            setups=_parse_setups(raw_setups),
        )

        needs_migration = False
        if isinstance(raw_setups, list):
            for row in raw_setups:
                if isinstance(row, dict) and _setup_row_needs_migration(row):
                    needs_migration = True
                    break
        if needs_migration:
            _save_settings(settings)

        return settings
    except Exception:
        _backup_corrupted_settings()
        return LauncherSettings()


def _backup_corrupted_settings() -> None:
    # Conserva il file illeggibile: il prossimo salvataggio altrimenti lo sovrascriverebbe.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SETTINGS_FILE.with_name(f"settings.corrupt_{stamp}.json")
    try:
        shutil.copy2(SETTINGS_FILE, backup)
    except Exception:
        pass


def _save_settings(settings: LauncherSettings) -> None:
    CFG_DIR.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_path(value: str) -> Path:
    return Path(value.strip().strip('"')).expanduser()


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
        for candidate in sorted(sw_base.rglob("SLDWORKS.exe"), reverse=True):
            if candidate.is_file():
                return candidate
    return None


class LauncherApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = _load_settings()
        self._timed_info_box: QMessageBox | None = None
        self.setWindowTitle(f"Launcher SolidWorks v{APP_VERSION}")
        self.setMinimumSize(400, 500)
        self.resize(400, 540)
        self.setStyleSheet(DARK_THEME)

        self._build_ui()
        self._populate_from_settings()
        self._render_quick_buttons()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)

        title = QLabel(f"Launcher SolidWorks v{APP_VERSION}")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        root_layout.addWidget(title)

        subtitle = QLabel("Stile PyQt6 applicato. Gestisci setup e avvia SolidWorks.")
        root_layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        self.tab_launch = QWidget()
        self.tab_manage = QWidget()
        self.tabs.addTab(self.tab_launch, "Avvio Rapido")
        self.tabs.addTab(self.tab_manage, "Gestione Setup")

        self._build_launch_tab()
        self._build_manage_tab()

    def _build_launch_tab(self) -> None:
        layout = QVBoxLayout(self.tab_launch)

        row = QHBoxLayout()
        btn_open_manage = QPushButton("Apri Gestione Setup")
        btn_open_manage.clicked.connect(lambda: self.tabs.setCurrentWidget(self.tab_manage))
        row.addWidget(btn_open_manage)
        layout.addLayout(row)

        self.quick_scroll = QScrollArea()
        self.quick_scroll.setWidgetResizable(True)
        self.quick_content = QWidget()
        self.quick_layout = QVBoxLayout(self.quick_content)
        self.quick_scroll.setWidget(self.quick_content)
        layout.addWidget(self.quick_scroll)

    def _build_manage_tab(self) -> None:
        layout = QVBoxLayout(self.tab_manage)

        box = QGroupBox("Setup")
        grid = QGridLayout(box)

        self.cmb_setup = QComboBox()
        self.cmb_setup.currentTextChanged.connect(self._on_setup_selected)

        self.edt_name = QLineEdit()
        self.edt_sldreg = QLineEdit()
        self.edt_sw_version = QLineEdit()
        self.edt_sw_exe = QLineEdit()

        self.chk_restore_system_options = QCheckBox("Opzioni sistema")
        self.chk_restore_toolbar_layout = QCheckBox("Layout toolbar")
        self.rb_toolbar_all = QRadioButton("Tutte")
        self.rb_toolbar_macros = QRadioButton("Solo macro")
        self.toolbar_mode_group = QButtonGroup(self)
        self.toolbar_mode_group.setExclusive(True)
        self.toolbar_mode_group.addButton(self.rb_toolbar_all)
        self.toolbar_mode_group.addButton(self.rb_toolbar_macros)
        self.chk_restore_keyboard_shortcuts = QCheckBox("Tasti rapidi")
        self.chk_restore_mouse_gestures = QCheckBox("Gesti mouse")
        self.chk_restore_menu_customizations = QCheckBox("Personalizzazioni menu")
        self.chk_restore_saved_views = QCheckBox("Viste salvate")

        self.chk_restore_system_options.setChecked(True)
        self.chk_restore_toolbar_layout.setChecked(True)
        self.rb_toolbar_all.setChecked(True)
        self.chk_restore_keyboard_shortcuts.setChecked(True)
        self.chk_restore_mouse_gestures.setChecked(True)
        self.chk_restore_menu_customizations.setChecked(True)
        self.chk_restore_saved_views.setChecked(True)
        self.chk_restore_toolbar_layout.toggled.connect(self._on_toolbar_layout_toggled)

        self.chk_cleanup = QCheckBox("Pulisci chiavi selezionate prima dell'import")
        self.chk_cleanup.setChecked(True)

        grid.addWidget(QLabel("Setup salvato"), 0, 0)
        grid.addWidget(self.cmb_setup, 0, 1, 1, 3)

        btn_new = QPushButton("Nuovo")
        btn_new.clicked.connect(self._new_setup)
        btn_del = QPushButton("Elimina")
        btn_del.clicked.connect(self._delete_setup)
        grid.addWidget(btn_new, 0, 4)
        grid.addWidget(btn_del, 0, 5)

        grid.addWidget(QLabel("Nome setup"), 1, 0)
        grid.addWidget(self.edt_name, 1, 1, 1, 3)
        btn_save = QPushButton("Salva/Aggiorna")
        btn_save.clicked.connect(self._save_setup)
        grid.addWidget(btn_save, 1, 4, 1, 2)

        grid.addWidget(QLabel("File configurazione (.sldreg)"), 2, 0)
        grid.addWidget(self.edt_sldreg, 2, 1, 1, 4)
        btn_sldreg = QPushButton("Sfoglia")
        btn_sldreg.clicked.connect(self._pick_sldreg)
        grid.addWidget(btn_sldreg, 2, 5)

        grid.addWidget(QLabel("Versione SolidWorks"), 3, 0)
        grid.addWidget(self.edt_sw_version, 3, 1, 1, 4)

        grid.addWidget(QLabel("Eseguibile SolidWorks (SLDWORKS.exe)"), 4, 0)
        grid.addWidget(self.edt_sw_exe, 4, 1, 1, 3)
        btn_sw_pick = QPushButton("Sfoglia")
        btn_sw_pick.clicked.connect(self._pick_solidworks)
        btn_sw_detect = QPushButton("Rileva")
        btn_sw_detect.clicked.connect(self._detect_solidworks)
        grid.addWidget(btn_sw_pick, 4, 4)
        grid.addWidget(btn_sw_detect, 4, 5)

        grid.addWidget(QLabel("Cosa configurare (wizard SW)"), 5, 0, 1, 6)
        grid.addWidget(self.chk_restore_system_options, 6, 0, 1, 3)
        grid.addWidget(self.chk_restore_keyboard_shortcuts, 6, 3, 1, 3)

        grid.addWidget(self.chk_restore_toolbar_layout, 7, 0, 1, 2)
        grid.addWidget(self.rb_toolbar_all, 7, 2)
        grid.addWidget(self.rb_toolbar_macros, 7, 3)
        grid.addWidget(self.chk_restore_mouse_gestures, 7, 4, 1, 2)

        grid.addWidget(self.chk_restore_menu_customizations, 8, 0, 1, 3)
        grid.addWidget(self.chk_restore_saved_views, 8, 3, 1, 3)

        grid.addWidget(self.chk_cleanup, 9, 0, 1, 6)

        btn_run = QPushButton("Carica Configurazione + Avvia SolidWorks")
        btn_run.clicked.connect(self._run_launcher)
        grid.addWidget(btn_run, 10, 0, 1, 6)

        layout.addWidget(box)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

    def _populate_from_settings(self) -> None:
        self.cmb_setup.blockSignals(True)
        self.cmb_setup.clear()
        self.cmb_setup.addItem("Nessuno")
        for setup in self.settings.setups:
            self.cmb_setup.addItem(setup.name)
        self.cmb_setup.blockSignals(False)

        self.edt_sldreg.setText(self.settings.sldreg_path)
        self.edt_sw_version.setText(self.settings.sw_version)
        self.edt_sw_exe.setText(self.settings.solidworks_path)

        if self.settings.active_setup and self.settings.active_setup in [s.name for s in self.settings.setups]:
            self.cmb_setup.setCurrentText(self.settings.active_setup)
            self._apply_setup(self._find_setup(self.settings.active_setup))
        else:
            self.cmb_setup.setCurrentText("Nessuno")

    def _render_quick_buttons(self) -> None:
        while self.quick_layout.count():
            item = self.quick_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self.settings.setups:
            self.quick_layout.addWidget(QLabel("Nessun setup salvato."))
            return

        active_key = self.settings.active_setup.strip().casefold()
        for setup in self.settings.setups:
            btn = QPushButton(f"{setup.name}  |  SW {setup.sw_version or '-'}")
            if setup.name.casefold() == active_key:
                btn.setObjectName("cfgLaunchButtonLast")
            else:
                btn.setObjectName("cfgLaunchButton")
            btn.clicked.connect(lambda _=False, name=setup.name: self._launch_saved_setup(name))
            self.quick_layout.addWidget(btn)

    def _find_setup(self, name: str) -> SetupProfile | None:
        key = name.strip().casefold()
        for setup in self.settings.setups:
            if setup.name.casefold() == key:
                return setup
        return None

    def _apply_setup(self, setup: SetupProfile | None) -> None:
        if setup is None:
            return
        self.edt_name.setText(setup.name)
        self.edt_sldreg.setText(setup.sldreg_path)
        self.edt_sw_version.setText(setup.sw_version)
        self.edt_sw_exe.setText(setup.solidworks_path)
        self.chk_cleanup.setChecked(bool(setup.cleanup_before_import))
        self.chk_restore_system_options.setChecked(bool(setup.restore_system_options))
        self.chk_restore_toolbar_layout.setChecked(bool(setup.restore_toolbar_layout))
        self.chk_restore_keyboard_shortcuts.setChecked(bool(setup.restore_keyboard_shortcuts))
        self.chk_restore_mouse_gestures.setChecked(bool(setup.restore_mouse_gestures))
        self.chk_restore_menu_customizations.setChecked(bool(setup.restore_menu_customizations))
        self.chk_restore_saved_views.setChecked(bool(setup.restore_saved_views))
        if _normalize_toolbar_mode(setup.restore_toolbar_mode) == "macro_only":
            self.rb_toolbar_macros.setChecked(True)
        else:
            self.rb_toolbar_all.setChecked(True)
        self._on_toolbar_layout_toggled(self.chk_restore_toolbar_layout.isChecked())

    def _on_toolbar_layout_toggled(self, enabled: bool) -> None:
        self.rb_toolbar_all.setEnabled(enabled)
        self.rb_toolbar_macros.setEnabled(enabled)

    def _on_setup_selected(self, selected_name: str) -> None:
        if selected_name == "Nessuno":
            self.settings.active_setup = ""
            self._render_quick_buttons()
            return
        setup = self._find_setup(selected_name)
        if setup:
            self.settings.active_setup = setup.name
            self._apply_setup(setup)
            self._render_quick_buttons()

    def _new_setup(self) -> None:
        self.cmb_setup.setCurrentText("Nessuno")
        self.edt_name.clear()
        self.chk_restore_system_options.setChecked(True)
        self.chk_restore_toolbar_layout.setChecked(True)
        self.rb_toolbar_all.setChecked(True)
        self.chk_restore_keyboard_shortcuts.setChecked(True)
        self.chk_restore_mouse_gestures.setChecked(True)
        self.chk_restore_menu_customizations.setChecked(True)
        self.chk_restore_saved_views.setChecked(True)
        self.chk_cleanup.setChecked(True)

    def _save_setup(self) -> None:
        name = self.edt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Setup", "Inserisci il nome setup.")
            return

        current = self._find_setup(name)
        if current is None:
            current = SetupProfile(name=name)
            self.settings.setups.append(current)

        current.sldreg_path = self.edt_sldreg.text().strip()
        current.sw_version = self.edt_sw_version.text().strip()
        current.solidworks_path = self.edt_sw_exe.text().strip()
        current.cleanup_before_import = bool(self.chk_cleanup.isChecked())
        current.restore_system_options = bool(self.chk_restore_system_options.isChecked())
        current.restore_toolbar_layout = bool(self.chk_restore_toolbar_layout.isChecked())
        current.restore_toolbar_mode = "macro_only" if self.rb_toolbar_macros.isChecked() else "all"
        current.restore_keyboard_shortcuts = bool(self.chk_restore_keyboard_shortcuts.isChecked())
        current.restore_mouse_gestures = bool(self.chk_restore_mouse_gestures.isChecked())
        current.restore_menu_customizations = bool(self.chk_restore_menu_customizations.isChecked())
        current.restore_saved_views = bool(self.chk_restore_saved_views.isChecked())

        self.settings.active_setup = name
        self._persist_settings()
        self._populate_from_settings()
        self._render_quick_buttons()
        self._log(f"Setup '{name}' salvato.")

    def _delete_setup(self) -> None:
        selected = self.cmb_setup.currentText().strip()
        if not selected or selected == "Nessuno":
            QMessageBox.warning(self, "Setup", "Seleziona un setup da eliminare.")
            return

        self.settings.setups = [s for s in self.settings.setups if s.name.casefold() != selected.casefold()]
        if self.settings.active_setup.casefold() == selected.casefold():
            self.settings.active_setup = ""

        self._persist_settings()
        self._populate_from_settings()
        self._render_quick_buttons()
        self._log(f"Setup '{selected}' eliminato.")

    def _pick_sldreg(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Seleziona file configurazione", "", "SolidWorks Reg (*.sldreg);;Tutti i file (*.*)")
        if selected:
            self.edt_sldreg.setText(selected)

    def _pick_solidworks(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Seleziona SLDWORKS.exe", "", "Eseguibili (*.exe);;Tutti i file (*.*)")
        if selected:
            self.edt_sw_exe.setText(selected)

    def _detect_solidworks(self) -> None:
        detected = _detect_solidworks_exe()
        if not detected:
            QMessageBox.warning(self, "SolidWorks", "SolidWorks non trovato automaticamente.")
            return
        self.edt_sw_exe.setText(str(detected))

    def _validate_paths(self) -> tuple[Path, Path] | None:
        sldreg_txt = self.edt_sldreg.text().strip()
        sw_exe_txt = self.edt_sw_exe.text().strip()

        if not sldreg_txt:
            QMessageBox.warning(self, "Launcher", "Seleziona il file .sldreg.")
            return None
        if not sw_exe_txt:
            QMessageBox.warning(self, "Launcher", "Seleziona il file SLDWORKS.exe.")
            return None

        sldreg = _normalize_path(sldreg_txt)
        sw_exe = _normalize_path(sw_exe_txt)

        if not sldreg.is_file() or sldreg.suffix.lower() != ".sldreg":
            QMessageBox.critical(self, "Launcher", f"File .sldreg non valido:\n{sldreg}")
            return None
        if not sw_exe.is_file() or sw_exe.name.lower() != "sldworks.exe":
            QMessageBox.critical(self, "Launcher", f"Eseguibile non valido:\n{sw_exe}")
            return None
        return sldreg, sw_exe

    def _collect_restore_options(self) -> RestoreOptions:
        options = RestoreOptions(
            system_options=bool(self.chk_restore_system_options.isChecked()),
            toolbar_layout=bool(self.chk_restore_toolbar_layout.isChecked()),
            toolbar_mode="macro_only" if self.rb_toolbar_macros.isChecked() else "all",
            keyboard_shortcuts=bool(self.chk_restore_keyboard_shortcuts.isChecked()),
            mouse_gestures=bool(self.chk_restore_mouse_gestures.isChecked()),
            menu_customizations=bool(self.chk_restore_menu_customizations.isChecked()),
            saved_views=bool(self.chk_restore_saved_views.isChecked()),
        )
        return _normalize_restore_options(options)

    def _show_timed_info(self, title: str, message: str, timeout_ms: int = 5000) -> None:
        if self._timed_info_box is not None:
            self._timed_info_box.close()
            self._timed_info_box.deleteLater()
            self._timed_info_box = None

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(message)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_button = box.button(QMessageBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.hide()
        box.setModal(False)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        timer = QTimer(box)
        timer.setSingleShot(True)

        def _close_box() -> None:
            box.accept()

        def _cleanup_ref() -> None:
            if self._timed_info_box is box:
                self._timed_info_box = None

        timer.timeout.connect(_close_box)
        box.finished.connect(_cleanup_ref)

        self._timed_info_box = box
        box.show()
        timer.start(timeout_ms)

    def _run_launcher(self) -> None:
        if os.name != "nt":
            QMessageBox.critical(self, "Launcher", "Questa app funziona solo su Windows.")
            return

        validated = self._validate_paths()
        if validated is None:
            return
        sldreg, sw_exe = validated

        if not self.edt_sw_version.text().strip():
            QMessageBox.warning(self, "Launcher", "Inserisci la versione SolidWorks.")
            return

        if _is_solidworks_running():
            answer = QMessageBox.question(
                self,
                "SolidWorks in esecuzione",
                "Sono presenti sessioni SolidWorks aperte.\n"
                "Vuoi chiuderle e continuare con import + nuovo avvio?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._log("Avvio annullato: sessioni SolidWorks gia aperte.")
                return

            closed, close_msg = _kill_solidworks_processes()
            if not closed:
                QMessageBox.critical(self, "SolidWorks", close_msg)
                return
            self._log("Sessioni SolidWorks chiuse prima dell'import.")

        options = self._collect_restore_options()
        if not options.has_any_selection():
            QMessageBox.warning(self, "Launcher", "Seleziona almeno una sezione da configurare.")
            return

        ok_import, import_msg = _import_sldreg(
            sldreg,
            restore_options=options,
            cleanup_before_import=bool(self.chk_cleanup.isChecked()),
        )
        if not ok_import:
            QMessageBox.critical(self, "Import .sldreg", import_msg)
            return

        try:
            subprocess.Popen([str(sw_exe)], cwd=str(sw_exe.parent))
        except Exception as exc:
            QMessageBox.critical(self, "Avvio SolidWorks", str(exc))
            return

        self._persist_settings()
        self._log(f"{import_msg} SolidWorks avviato.")
        self._show_timed_info("Launcher", "Configurazione applicata e SolidWorks avviato.")

    def _launch_saved_setup(self, setup_name: str) -> None:
        setup = self._find_setup(setup_name)
        if setup is None:
            QMessageBox.warning(self, "Setup", "Setup non trovato.")
            return
        self.settings.active_setup = setup.name
        self.cmb_setup.setCurrentText(setup.name)
        self._apply_setup(setup)
        self._persist_settings()
        self._render_quick_buttons()
        self._run_launcher()

    def _log(self, text: str) -> None:
        self.log_box.append(text)

    def _persist_settings(self) -> None:
        self.settings.sldreg_path = self.edt_sldreg.text().strip()
        self.settings.sw_version = self.edt_sw_version.text().strip()
        self.settings.solidworks_path = self.edt_sw_exe.text().strip()
        _save_settings(self.settings)


def main() -> None:
    qt_app = QApplication(sys.argv)
    window = LauncherApp()
    window.show()
    qt_app.exec()


if __name__ == "__main__":
    main()
