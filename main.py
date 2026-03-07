from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
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
try:
    APP_VERSION = (DATA_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.9.7"
except Exception:
    APP_VERSION = "0.9.7"


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
    cleanup_before_import: bool = True


@dataclass
class LauncherSettings:
    sldreg_path: str = ""
    sw_version: str = ""
    solidworks_path: str = ""
    active_setup: str = ""
    setups: list[SetupProfile] = field(default_factory=list)


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
        parsed.append(
            SetupProfile(
                name=name,
                sldreg_path=str(row.get("sldreg_path", "")).strip(),
                sw_version=str(row.get("sw_version", "")).strip(),
                solidworks_path=str(row.get("solidworks_path", "")).strip(),
                cleanup_before_import=bool(row.get("cleanup_before_import", True)),
            )
        )
    return parsed


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

        grid.addWidget(self.chk_cleanup, 5, 0, 1, 6)

        btn_run = QPushButton("Carica Configurazione + Avvia SolidWorks")
        btn_run.clicked.connect(self._run_launcher)
        grid.addWidget(btn_run, 6, 0, 1, 6)

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

        # Import base della configurazione
        completed = subprocess.run(["reg", "import", str(sldreg)], capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            msg = (completed.stderr or completed.stdout or "Import .sldreg fallito.").strip()
            QMessageBox.critical(self, "Import .sldreg", msg)
            return

        try:
            subprocess.Popen([str(sw_exe)], cwd=str(sw_exe.parent))
        except Exception as exc:
            QMessageBox.critical(self, "Avvio SolidWorks", str(exc))
            return

        self._persist_settings()
        self._log("Configurazione caricata e SolidWorks avviato.")

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
        selected = self.cmb_setup.currentText().strip()
        self.settings.active_setup = "" if selected == "Nessuno" else selected
        _save_settings(self.settings)


def main() -> None:
    qt_app = QApplication(sys.argv)
    window = LauncherApp()
    window.show()
    qt_app.exec()


if __name__ == "__main__":
    main()
