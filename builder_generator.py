# -*- coding: utf-8 -*-
"""
Генератор код-билдеров для правого рельса (customtkinter).
Вставляешь фрагмент описания модели, отмечаешь нужные параметры,
тонко настраиваешь виджеты — нажимаешь «Сгенерировать» и получаешь
готовые куски кода для вставки в твой основной app.py.

Автор: ты и твой будущий ИИ :)
"""

import re
import tkinter as tk
import customtkinter as ctk
import tkinter.messagebox as mb
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional
import os
import json

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ------- эвристики дефолтных диапазонов -------
SLIDER_PRESETS = {
    "temperature": (0.0, 2.0, 0.05),
    "top_p": (0.0, 1.0, 0.01),
    "presence_penalty": (-2.0, 2.0, 0.1),
    "frequency_penalty": (-2.0, 2.0, 0.1),
    "max_image_resolution": (0.1, 2.0, 0.1),
}


def infer_slider_bounds(name: str, default: float) -> tuple[float, float, float]:
    if name in SLIDER_PRESETS:
        return SLIDER_PRESETS[name]
    # общие эвристики
    if 0.0 <= default <= 1.0:
        return (0.0, 1.0, 0.01)
    if 0.0 <= default <= 2.0:
        return (0.0, 2.0, 0.05)
    if -2.0 <= default <= 2.0:
        return (-2.0, 2.0, 0.1)
    # fallback
    return (
        0.0,
        max(1.0, round(default * 2, 2)),
        max(0.01, round(max(1.0, default) / 100, 3)),
    )


# ------- модели данных -------
@dataclass
class ParamSpec:
    name: str
    raw_default: Any
    enabled: bool = True
    widget_type: str = ""  # "slider" | "int" | "checkbox" | "text" | "select"
    min_val: Optional[float] = None  # original default (for slider/int)
    max_val: Optional[float] = None  # original default (for slider/int)
    step: Optional[float] = None  # original default (for slider)
    options: Optional[List[str]] = None  # original list for select
    # user overrides (None means use original)
    override_min: Optional[float] = None
    override_max: Optional[float] = None
    override_step: Optional[float] = None
    override_default: Optional[Any] = None
    override_options: Optional[List[str]] = None

    def infer_widget(self):
        v = self.raw_default
        if isinstance(v, bool):
            self.widget_type = "checkbox"
        elif isinstance(v, float):
            self.widget_type = "slider"
            self.min_val, self.max_val, self.step = infer_slider_bounds(self.name, v)
        elif isinstance(v, int):
            self.widget_type = "int"
        else:
            self.widget_type = "text"

    def to_python_literal(self):
        v = self.raw_default
        if isinstance(v, str):
            return f'"{v}"'
        if isinstance(v, bool):
            return "True" if v else "False"
        return str(v)


@dataclass
class ModelSpec:
    model_id: str
    params: List[ParamSpec] = field(default_factory=list)


# ------- парсер входного текста -------
def parse_model_block(text: str) -> ModelSpec:
    """
    Поддерживает куски вида:
    "deepseek-ai/deepseek-v3",
        input={
            "top_p": 1,
            "prompt": "What ...",
            "max_tokens": 1024,
            "temperature": 0.6,
            "presence_penalty": 0,
            "frequency_penalty": 0
        }
    """
    # модель — между кавычками до запятой
    m_model = re.search(r'"([^"]+)"\s*,', text)
    model_id = m_model.group(1).strip() if m_model else "my/model"

    # вытащить блок input={...}
    m_input = re.search(r"input\s*=\s*\{(.+?)\}", text, re.S)
    inside = m_input.group(1) if m_input else ""

    # распарсить key: value построчно (простые случаи)
    params: List[ParamSpec] = []
    for line in inside.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        # вид: "key": value
        m = re.match(r'"([^"]+)"\s*:\s*(.+)$', line)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2).strip()

        # привести значение к python типу по простым эвристикам
        if re.fullmatch(r"true|false", val, re.I):
            pyv = val.lower() == "true"
        elif re.fullmatch(r"-?\d+\.\d+", val):
            pyv = float(val)
        elif re.fullmatch(r"-?\d+", val):
            pyv = int(val)
        elif re.fullmatch(r'"[^"]*"', val):
            pyv = val.strip('"')
        else:
            # оставим строкой без кавычек
            pyv = val.strip('"')

        p = ParamSpec(name=key, raw_default=pyv)
        p.infer_widget()
        params.append(p)

    return ModelSpec(model_id=model_id, params=params)


# ------- UI генератора -------
class GeneratorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Builder Generator – CTk")
        self.minsize(1200, 760)

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # LEFT: input + parsed params
        left = ctk.CTkFrame(self, corner_radius=12, fg_color=("gray10", "gray12"))
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(left, text="Вставь описание модели").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        self.source_tb = ctk.CTkTextbox(left, height=160)
        self.source_tb.grid(row=1, column=0, sticky="we", padx=12)

        parse_btn = ctk.CTkButton(left, text="Разобрать →", command=self.on_parse)
        parse_btn.grid(row=1, column=1, sticky="e", padx=12)

        # parsed params list
        self.params_frame = ctk.CTkScrollableFrame(
            left, height=380, corner_radius=12, fg_color=("gray11", "gray13")
        )
        self.params_frame.grid(
            row=2, column=0, columnspan=2, sticky="nsew", padx=12, pady=(12, 12)
        )
        self.params_frame.grid_columnconfigure(0, weight=1)

        # RIGHT: preview + output
        right = ctk.CTkFrame(self, corner_radius=12, fg_color=("gray10", "gray12"))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        # model id
        top = ctk.CTkFrame(right, fg_color=("gray11", "gray13"), corner_radius=12)
        top.grid(row=0, column=0, sticky="we", padx=12, pady=(12, 6))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text="Model ID").grid(
            row=0, column=0, padx=12, pady=10, sticky="w"
        )
        self.model_id_var = tk.StringVar(value="")
        ctk.CTkEntry(
            top, textvariable=self.model_id_var, placeholder_text="provider/model"
        ).grid(row=0, column=1, padx=12, pady=10, sticky="we")

        # export settings
        exp = ctk.CTkFrame(right, fg_color=("gray11", "gray13"), corner_radius=12)
        exp.grid(row=0, column=0, sticky="we", padx=12, pady=(6, 6))
        exp.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(exp, text="Папка для конфигов").grid(
            row=0, column=0, padx=12, pady=10, sticky="w"
        )
        self.out_dir_var = tk.StringVar(value="models_conf/text")
        ctk.CTkEntry(
            exp, textvariable=self.out_dir_var, placeholder_text="models_conf/text"
        ).grid(row=0, column=1, padx=12, pady=10, sticky="we")
        ctk.CTkButton(
            exp, text="Сохранить конфиг (JSON)", command=self.save_config
        ).grid(row=0, column=2, padx=12, pady=10)
        # model kind selector
        ctk.CTkLabel(exp, text="Тип").grid(
            row=1, column=0, padx=12, pady=(0, 12), sticky="w"
        )
        self.kind_var = tk.StringVar(value="text")
        ctk.CTkOptionMenu(
            exp,
            variable=self.kind_var,
            values=["text", "img", "video", "audio"],
            command=lambda _=None: self.on_kind_change(),
        ).grid(row=1, column=1, padx=12, pady=(0, 12), sticky="w")

        # preview + generate
        mid = ctk.CTkFrame(right, fg_color=("gray11", "gray13"), corner_radius=12)
        mid.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(mid, text="Превью панели настроек").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        self.preview = ctk.CTkScrollableFrame(
            mid, height=360, corner_radius=12, fg_color=("gray12", "gray14")
        )
        self.preview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        btns = ctk.CTkFrame(mid, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="we", padx=12, pady=(0, 12))
        ctk.CTkButton(btns, text="Обновить превью", command=self.refresh_preview).pack(
            side="left"
        )

        # ensure preview is expandable
        mid.grid_rowconfigure(1, weight=1)

        # (output code panel removed)

        # state
        self.current_params: List[ParamSpec] = []

    # ------- действия -------
    def on_parse(self):
        spec = parse_model_block(self.source_tb.get("1.0", "end"))
        self.model_id_var.set(spec.model_id)
        self.current_params = spec.params
        self.render_param_rows()
        self.refresh_preview()
    # build_template_skeleton, get_template_dict, and infer_coercion removed

    def render_param_rows(self):
        # очистить
        for w in list(self.params_frame.winfo_children()):
            w.destroy()

        # Общая схема колонок: 0:chk | 1:name | 2:type | 3:min | 4:max | 5:step | 6:default (stretch)
        COL_SPECS = {
            0: {"minsize": 46, "weight": 0},
            1: {"minsize": 160, "weight": 0},
            2: {"minsize": 140, "weight": 0},
            3: {"minsize": 90, "weight": 0},
            4: {"minsize": 90, "weight": 0},
            5: {"minsize": 90, "weight": 0},
            6: {"minsize": 120, "weight": 1},  # default тянется
        }

        def config_cols(container):
            for c, spec in COL_SPECS.items():
                container.grid_columnconfigure(
                    c, minsize=spec["minsize"], weight=spec["weight"]
                )

        # Заголовок
        hdr = ctk.CTkFrame(self.params_frame, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="we", padx=8, pady=(8, 0))
        config_cols(hdr)
        headers = ["Вкл", "Имя", "Тип"]
        for i, text in enumerate(headers):
            ctk.CTkLabel(hdr, text=text).grid(row=0, column=i, padx=6, sticky="w")

        # Строки параметров (строим через внутреннюю функцию, чтобы замкнуть переменные)
        def add_row(grid_index: int, ps: ParamSpec):
            row = ctk.CTkFrame(self.params_frame, fg_color=("gray12", "gray14"))
            row.grid(row=grid_index, column=0, sticky="we", padx=8, pady=6)
            config_cols(row)

            # enable checkbox
            en_var = tk.BooleanVar(value=ps.enabled)
            en_cb = ctk.CTkCheckBox(row, text="", width=30, variable=en_var)
            en_cb.grid(row=0, column=0, padx=6, sticky="w")

            # name label
            name_lbl = ctk.CTkLabel(row, text=ps.name)
            name_lbl.grid(row=0, column=1, padx=6, sticky="w")

            # type menu
            if not ps.widget_type:
                ps.infer_widget()
            type_var = tk.StringVar(value=ps.widget_type)
            type_menu = ctk.CTkOptionMenu(
                row,
                values=["slider", "int", "checkbox", "text", "select"],
                variable=type_var,
                width=130,
            )
            type_menu.grid(row=0, column=2, padx=6, sticky="we")

            # empty by default -> show placeholders with originals; user input becomes override_*
            def sync_num(entry_widget: ctk.CTkEntry, which: str):
                txt = entry_widget.get().strip()
                try:
                    val = float(txt) if txt != "" else None
                except Exception:
                    val = None
                if which == "min":
                    ps.override_min = val
                elif which == "max":
                    ps.override_max = val
                else:
                    ps.override_step = val

            e_min = ctk.CTkEntry(
                row,
                width=84,
                placeholder_text=("min" if ps.min_val is None else str(ps.min_val)),
                placeholder_text_color=("gray65", "gray45"),
            )
            e_max = ctk.CTkEntry(
                row,
                width=84,
                placeholder_text=("max" if ps.max_val is None else str(ps.max_val)),
                placeholder_text_color=("gray65", "gray45"),
            )
            e_step = ctk.CTkEntry(
                row,
                width=84,
                placeholder_text=("step" if ps.step is None else str(ps.step)),
                placeholder_text_color=("gray65", "gray45"),
            )
            e_min.bind("<KeyRelease>", lambda _e, ew=e_min: sync_num(ew, "min"))
            e_max.bind("<KeyRelease>", lambda _e, ew=e_max: sync_num(ew, "max"))
            e_step.bind("<KeyRelease>", lambda _e, ew=e_step: sync_num(ew, "step"))

            # select values
            def on_opts_change(_e=None, ew=None):
                txt = ew.get().strip() if ew is not None else ""
                if txt:
                    ps.override_options = [
                        s.strip() for s in txt.split(",") if s.strip()
                    ]
                else:
                    ps.override_options = None
                self.refresh_preview()

            select_entry = ctk.CTkEntry(
                row,
                placeholder_text=(
                    "values: a,b,c" if not ps.options else ",".join(ps.options)
                ),
                placeholder_text_color=("gray65", "gray45"),
            )
            select_entry.bind(
                "<KeyRelease>", lambda _e, ew=select_entry: on_opts_change(_e, ew)
            )

            # default controls
            placeholder_val = (
                str(ps.raw_default) if ps.raw_default is not None else "default"
            )
            def_entry = ctk.CTkEntry(
                row,
                placeholder_text=placeholder_val,
                placeholder_text_color=("gray65", "gray45"),
            )

            def on_default_text():
                txt = def_entry.get().strip()
                if txt == "":
                    ps.override_default = None
                else:
                    if ps.widget_type == "slider":
                        try:
                            ps.override_default = float(txt)
                        except Exception:
                            ps.override_default = None
                    elif ps.widget_type == "int":
                        try:
                            ps.override_default = int(float(txt))
                        except Exception:
                            ps.override_default = None
                    elif ps.widget_type == "checkbox":
                        low = txt.lower()
                        if low in ("true", "1", "yes", "on"):
                            ps.override_default = True
                        elif low in ("false", "0", "no", "off"):
                            ps.override_default = False
                        else:
                            ps.override_default = None
                    else:
                        ps.override_default = txt
                self.refresh_preview()

            def_entry.bind("<KeyRelease>", lambda _e: on_default_text())

            def_bool_var = tk.StringVar(
                value=(
                    "True"
                    if bool(
                        ps.override_default
                        if ps.override_default is not None
                        else ps.raw_default
                    )
                    else "False"
                )
            )
            def_bool_menu = ctk.CTkOptionMenu(
                row,
                values=["True", "False"],
                variable=def_bool_var,
                command=lambda val: (
                    setattr(ps, "override_default", val == "True"),
                    self.refresh_preview(),
                ),
            )

            # helpers
            row_widgets = [e_min, e_max, e_step, select_entry, def_entry, def_bool_menu]

            def hide_all():
                for w in row_widgets:
                    try:
                        w.grid_forget()
                    except Exception:
                        pass

            def show_slider():
                e_min.grid(row=0, column=3, padx=6, sticky="we")
                e_max.grid(row=0, column=4, padx=6, sticky="we")
                e_step.grid(row=0, column=5, padx=6, sticky="we")
                def_entry.grid(row=0, column=6, padx=6, sticky="we")

            def show_int():
                e_min.grid(row=0, column=3, padx=6, sticky="we")
                e_max.grid(row=0, column=4, padx=6, sticky="we")
                def_entry.grid(row=0, column=6, padx=6, sticky="we")

            def show_checkbox():
                def_bool_menu.grid(row=0, column=6, padx=6, sticky="we")

            def show_text():
                def_entry.grid(row=0, column=6, padx=6, sticky="we")

            def show_select():
                select_entry.grid(row=0, column=3, columnspan=4, padx=6, sticky="we")

            def apply_type_ui():
                hide_all()
                tp = type_var.get()
                ps.widget_type = tp
                if tp == "slider":
                    # init bounds if empty
                    if ps.min_val is None or ps.max_val is None or ps.step is None:
                        default = (
                            float(ps.raw_default)
                            if isinstance(ps.raw_default, (int, float))
                            else 0.5
                        )
                        mn, mx, st = infer_slider_bounds(ps.name, default)
                        ps.min_val, ps.max_val, ps.step = mn, mx, st
                    # update placeholders to reflect current originals
                    e_min.configure(placeholder_text=("min" if ps.min_val is None else str(ps.min_val)))
                    e_max.configure(placeholder_text=("max" if ps.max_val is None else str(ps.max_val)))
                    e_step.configure(placeholder_text=("step" if ps.step is None else str(ps.step)))
                    show_slider()
                elif tp == "int":
                    show_int()
                elif tp == "checkbox":
                    show_checkbox()
                elif tp == "select":
                    show_select()
                else:
                    show_text()

            def apply_enabled_ui():
                if not en_var.get():
                    hide_all()
                    type_menu.grid_remove()
                else:
                    type_menu.grid()
                    apply_type_ui()

            # bind events
            type_menu.configure(command=lambda _choice=None: apply_type_ui())
            en_cb.configure(
                command=lambda: (
                    setattr(ps, "enabled", en_var.get()),
                    apply_enabled_ui(),
                    self.refresh_preview(),
                )
            )

            # initial
            apply_enabled_ui()

        for idx, p in enumerate(self.current_params, start=1):
            add_row(idx, p)

    def refresh_preview(self):
        # очистить
        for w in list(self.preview.winfo_children()):
            w.destroy()

        # helpers для превью
        def slider_row(parent, label, val, mn, mx, st):
            var = tk.DoubleVar(value=float(val))
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=label).grid(
                row=0, column=0, padx=12, pady=(8, 4), sticky="w"
            )
            ctk.CTkSlider(
                row,
                from_=mn,
                to=mx,
                number_of_steps=max(1, int((mx - mn) / max(st, 0.001))),
                variable=var,
            ).grid(row=0, column=1, padx=12, pady=(8, 4), sticky="we")
            ctk.CTkLabel(
                row, text=f"{float(var.get()):.2f}", text_color=("gray75", "gray60")
            ).grid(row=0, column=2, padx=(0, 12))
            row.pack(fill="x")

        def int_entry(parent, label, val):
            ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=12, pady=(8, 4))
            ctk.CTkEntry(parent, placeholder_text=str(val)).pack(fill="x", padx=12)

        def checkbox(parent, label, val):
            var = tk.BooleanVar(value=bool(val))
            ctk.CTkCheckBox(parent, text=label, variable=var).pack(
                anchor="w", padx=12, pady=(8, 0)
            )

        def text_entry(parent, label, val):
            ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=12, pady=(8, 4))
            ctk.CTkEntry(parent, placeholder_text=str(val)).pack(fill="x", padx=12)

        # нарисовать включенные
        any_drawn = False
        for p in self.current_params:
            if not p.enabled:
                continue
            any_drawn = True
            if p.widget_type == "slider":
                mn = (
                    p.override_min
                    if p.override_min is not None
                    else (p.min_val if p.min_val is not None else 0.0)
                )
                mx = (
                    p.override_max
                    if p.override_max is not None
                    else (p.max_val if p.max_val is not None else 1.0)
                )
                st = (
                    p.override_step
                    if p.override_step is not None
                    else (p.step if p.step is not None else 0.01)
                )
                base_src = (
                    p.override_default
                    if p.override_default is not None
                    else p.raw_default
                )
                base = float(base_src) if isinstance(base_src, (int, float)) else 0.5
                slider_row(self.preview, p.name, base, float(mn), float(mx), float(st))
            elif p.widget_type == "int":
                dsrc = (
                    p.override_default
                    if p.override_default is not None
                    else p.raw_default
                )
                try:
                    v = int(float(dsrc))
                except Exception:
                    v = 0
                int_entry(self.preview, p.name, v)
            elif p.widget_type == "checkbox":
                v = (
                    p.override_default
                    if p.override_default is not None
                    else p.raw_default
                )
                checkbox(self.preview, p.name, bool(v))
            elif p.widget_type == "select":
                values = (
                    p.override_options
                    if (isinstance(p.override_options, list) and p.override_options)
                    else (
                        p.options if isinstance(p.options, list) and p.options else []
                    )
                )
                # ensure default is present in values
                base_def = (
                    p.override_default
                    if p.override_default is not None
                    else p.raw_default
                )
                def_val = str(base_def) if base_def is not None else ""
                if def_val and def_val not in values:
                    values = [def_val] + values
                if not values:
                    values = ["option1", "option2"]
                var = tk.StringVar(value=def_val or values[0])
                ctk.CTkLabel(self.preview, text=p.name).pack(
                    anchor="w", padx=12, pady=(8, 4)
                )
                ctk.CTkOptionMenu(self.preview, values=values, variable=var).pack(
                    fill="x", padx=12
                )
            else:
                v = (
                    p.override_default
                    if p.override_default is not None
                    else p.raw_default
                )
                text_entry(self.preview, p.name, v)

        if not any_drawn:
            ctk.CTkLabel(self.preview, text="Нет выбранных параметров").pack(
                padx=12, pady=12, anchor="w"
            )

    def on_kind_change(self):
        kind = self.kind_var.get().strip().lower()
        # If the out dir is one of our defaults, switch it to the selected kind
        if self.out_dir_var.get().startswith("models_conf/"):
            self.out_dir_var.set(f"models_conf/{kind}")

    def validate_current(self) -> tuple[bool, list[str]]:
        """Validate enabled parameters according to their widget type.
        Returns (ok, errors)."""
        errs: list[str] = []

        def to_float(x):
            try:
                return float(x)
            except Exception:
                return None

        def to_int(x):
            try:
                # allow "10.0" -> 10
                return int(float(x))
            except Exception:
                return None

        model_id = (self.model_id_var.get() or "").strip()
        if not model_id:
            errs.append("Укажите Model ID")

        any_enabled = any(p.enabled for p in self.current_params)
        if not any_enabled:
            errs.append("Выберите хотя бы один параметр (галочка 'Вкл')")

        for p in self.current_params:
            if not p.enabled:
                continue
            t = (p.widget_type or "").lower()
            eff_min = p.override_min if p.override_min is not None else p.min_val
            eff_max = p.override_max if p.override_max is not None else p.max_val
            eff_step = p.override_step if p.override_step is not None else p.step
            eff_def = (
                p.override_default if p.override_default is not None else p.raw_default
            )
            eff_opts = (
                p.override_options if p.override_options is not None else p.options
            )

            if t == "slider":
                mn = eff_min
                mx = eff_max
                st = eff_step
                if mn is None or mx is None or st is None:
                    errs.append(f"{p.name}: заполните min/max/step для slider")
                else:
                    try:
                        mn_f = float(mn)
                        mx_f = float(mx)
                        st_f = float(st)
                        if not (mx_f > mn_f):
                            errs.append(f"{p.name}: max должен быть > min")
                        if not (st_f > 0):
                            errs.append(f"{p.name}: step должен быть > 0")
                    except Exception:
                        errs.append(f"{p.name}: min/max/step должны быть числами")
                d = eff_def
                d_f = to_float(d)
                if d_f is None:
                    errs.append(f"{p.name}: default для slider должен быть числом")
                elif mn is not None and mx is not None:
                    try:
                        if not (float(mn) <= d_f <= float(mx)):
                            errs.append(
                                f"{p.name}: default должен попадать в [min,max]"
                            )
                    except Exception:
                        pass

            elif t == "int":
                mn = eff_min
                mx = eff_max
                if mn is None or mx is None:
                    errs.append(f"{p.name}: укажите min и max для int")
                else:
                    try:
                        if not (float(mx) >= float(mn)):
                            errs.append(f"{p.name}: max должен быть ≥ min")
                    except Exception:
                        errs.append(f"{p.name}: min/max должны быть числами")
                d_i = to_int(eff_def)
                if d_i is None:
                    errs.append(f"{p.name}: default для int должен быть целым числом")
                elif mn is not None and mx is not None:
                    try:
                        if not (float(mn) <= d_i <= float(mx)):
                            errs.append(
                                f"{p.name}: default должен быть в диапазоне [min,max]"
                            )
                    except Exception:
                        pass

            elif t == "checkbox":
                if not isinstance(eff_def, bool):
                    # допускаем строку true/false
                    s = str(eff_def).strip().lower()
                    if s in ("true", "1", "yes", "on"):
                        pass
                    elif s in ("false", "0", "no", "off"):
                        pass
                    else:
                        errs.append(
                            f"{p.name}: default для checkbox должен быть True/False"
                        )

            elif t == "select":
                if not eff_opts or not isinstance(eff_opts, list):
                    errs.append(f"{p.name}: заполните values (список через запятую)")

            else:  # text
                # текст не валидируем
                pass

        return (len(errs) == 0, errs)

    def build_config_dict(self) -> dict:
        model_id = self.model_id_var.get().strip() or "my/model"
        controls = []
        for p in self.current_params:  # сохраняем все, даже если выключены
            # эффективные значения (override приоритетнее оригинала)
            eff_min = p.override_min if p.override_min is not None else p.min_val
            eff_max = p.override_max if p.override_max is not None else p.max_val
            eff_step = p.override_step if p.override_step is not None else p.step
            eff_def = (
                p.override_default if p.override_default is not None else p.raw_default
            )
            eff_opts = (
                p.override_options if p.override_options is not None else p.options
            )

            item = {
                "key": p.name,
                "type": p.widget_type,
                "default": eff_def,
                "enabled": bool(p.enabled),
                "hidden": (not p.enabled),
            }
            if p.widget_type == "slider":
                if eff_min is not None:
                    item["min"] = float(eff_min)
                if eff_max is not None:
                    item["max"] = float(eff_max)
                if eff_step is not None:
                    item["step"] = float(eff_step)
            elif p.widget_type == "int":
                if eff_min is not None:
                    item["min"] = int(float(eff_min))
                if eff_max is not None:
                    item["max"] = int(float(eff_max))
            elif p.widget_type == "select":
                item["values"] = eff_opts or []

            controls.append(item)

        return {
            "kind": self.kind_var.get().strip().lower(),
            "model_id": model_id,
            "label": model_id.split("/")[-1],
            "controls": controls,
        }

    def save_config(self):
        ok, errors = self.validate_current()
        if not ok:
            mb.showerror("Проверьте поля", "\n".join(errors))
            return

        cfg = self.build_config_dict()
        out_dir = self.out_dir_var.get().strip() or "models_conf/text"
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", cfg["model_id"]).strip("_").lower()
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{safe_name}.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            mb.showerror("Ошибка", f"Ошибка сохранения: {e}")
            return
        mb.showinfo("Сохранено", f"Конфиг сохранён:\n{out_path}")


if __name__ == "__main__":
    GeneratorApp().mainloop()
