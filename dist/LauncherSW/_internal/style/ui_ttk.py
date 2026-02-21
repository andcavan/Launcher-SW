from __future__ import annotations
from tkinter import ttk, font as tkfont

def configure_treeview_style(root, palette) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    try:
        base_font = tkfont.nametofont("TkDefaultFont")
        base_family = str(base_font.cget("family"))
        base_size = int(base_font.cget("size"))
    except Exception:
        base_family = "Segoe UI"
        base_size = 10

    fixed_size = 14
    tree_size = -fixed_size if base_size < 0 else fixed_size
    tree_font = (base_family, tree_size)
    heading_font = (base_family, tree_size, "bold")
    row_h = max(24, abs(tree_size) + 15)

    style.configure(
        "Treeview",
        background=palette.panel_2,
        fieldbackground=palette.panel_2,
        foreground=palette.fg,
        font=tree_font,
        bordercolor=palette.border,
        lightcolor=palette.border,
        darkcolor=palette.border,
        relief="flat",
        rowheight=row_h,
    )
    style.map(
        "Treeview",
        background=[("selected", palette.selection_bg)],
        foreground=[("selected", palette.selection_fg)],
    )

    style.configure(
        "Treeview.Heading",
        background=palette.panel,
        foreground=palette.fg,
        font=heading_font,
        relief="flat",
        borderwidth=1,
    )
    style.map(
        "Treeview.Heading",
        background=[("active", palette.panel)],
        foreground=[("active", palette.fg)],
    )

    # Scrollbar Style
    style.configure(
        "TScrollbar",
        troughcolor=palette.panel_2,
        background=palette.scrollbar_button,
        bordercolor=palette.panel_2,
        arrowcolor=palette.fg,
        relief="flat",
    )
    style.map(
        "TScrollbar",
        background=[
            ("active", palette.scrollbar_button_hover),
        ],
    )
