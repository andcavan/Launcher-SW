from __future__ import annotations
from dataclasses import dataclass

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover
    ctk = None

STYLE_NAME = "MyStyle01"
STYLE_VERSION = "1.0.0"

@dataclass(frozen=True)
class Palette:
    bg: str
    fg: str
    muted_fg: str
    panel: str
    panel_2: str
    border: str
    accent: str
    accent_2: str
    ok: str
    warn: str
    err: str
    entry_bg: str
    entry_fg: str
    selection_bg: str
    selection_fg: str
    disabled_bg: str
    disabled_fg: str
    sash: str
    scrollbar_button: str
    scrollbar_button_hover: str


DARK = Palette(
    bg="#0e1116",
    fg="#e8eef6",
    muted_fg="#a9b4c3",
    panel="#141a22",
    panel_2="#10161d",
    border="#273245",
    accent="#3b82f6",
    accent_2="#22c55e",
    ok="#22c55e",
    warn="#f59e0b",
    err="#ef4444",
    entry_bg="#0f1620",
    entry_fg="#e8eef6",
    selection_bg="#2a3a52",
    selection_fg="#e8eef6",
    disabled_bg="#1c232e",
    disabled_fg="#8892a1",
    sash="#0e1116",
    scrollbar_button="#273245",
    scrollbar_button_hover="#3e4e6b",
)

LIGHT = Palette(
    bg="#f6f7fb",
    fg="#111827",
    muted_fg="#4b5563",
    panel="#ffffff",
    panel_2="#f1f5f9",
    border="#cbd5e1",
    accent="#2563eb",
    accent_2="#16a34a",
    ok="#16a34a",
    warn="#d97706",
    err="#dc2626",
    entry_bg="#ffffff",
    entry_fg="#111827",
    selection_bg="#dbeafe",
    selection_fg="#111827",
    disabled_bg="#f3f4f6",
    disabled_fg="#9ca3af",
    sash="#f6f7fb",
    scrollbar_button="#cbd5e1",
    scrollbar_button_hover="#a8b5c4",
)

def apply_style(dark: bool = True) -> Palette:
    palette = DARK if dark else LIGHT
    if ctk is not None:
        ctk.set_appearance_mode("Dark" if dark else "Light")
        ctk.set_default_color_theme("dark-blue" if dark else "blue")
    return palette
