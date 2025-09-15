# -*- coding: utf-8 -*-
"""
CTk — вкладка ТЕКСТ в стиле твоих скринов.
Только интерфейс, без логики. Все места для API помечены TODO.
Горячие клавиши: Ctrl/⌘+Enter — Отправить, Esc — Очистить поле.
"""
import tkinter as tk
import customtkinter as ctk

import os, glob, json
from tkinter import messagebox as mb

import threading
import time

try:
    import replicate
except Exception:
    replicate = None

# .env support
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    load_dotenv = None

APP_TITLE = "AI Workbench — Text (CTk)"
APP_MIN_W, APP_MIN_H = 1240, 760

# ---- helpers to format model output ----


def _as_whisper_transcription(output):
    if isinstance(output, dict):
        t = output.get("transcription")
        if isinstance(t, str) and t.strip():
            return t
    if isinstance(output, list) and output and isinstance(output[0], dict):
        t = output[0].get("transcription")
        if isinstance(t, str) and t.strip():
            return t
    return None


def format_prediction_output(output) -> str:
    t = _as_whisper_transcription(output)
    if t is not None:
        return t
    if isinstance(output, list):
        urls = [
            x
            for x in output
            if isinstance(x, str) and x.startswith(("http://", "https://"))
        ]
        if urls:
            return "\n".join(urls)
        if len(output) == 1 and isinstance(output[0], str):
            return output[0]
        try:
            import json as _json

            return _json.dumps(output, ensure_ascii=False, indent=2)
        except Exception:
            return str(output)
    if isinstance(output, str):
        return output
    try:
        import json as _json

        return _json.dumps(output, ensure_ascii=False, indent=2)
    except Exception:
        return str(output)


# ---- coercion helpers (bring types to what API expects) ----
JSON_LIKE_KEYS = {
    "tools",
    "messages",
    "documents",
    "chat_template_kwargs",
    "image_input",
}


def _parse_json_if_needed(val):
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        s = val.strip()
        if (s.startswith("[") and s.endswith("]")) or (
            s.startswith("{") and s.endswith("}")
        ):
            try:
                return json.loads(s)
            except Exception:
                return val
    return val


def _coerce_value_by_type(ctrl_type: str, key: str, val):
    """Coerce a single value based on control type and known json-like keys."""
    if ctrl_type == "checkbox":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    if ctrl_type == "slider":
        try:
            return float(val)
        except Exception:
            return val
    if ctrl_type == "int":
        try:
            return int(float(val))
        except Exception:
            return val
    # text/select: keep string, but parse JSON for known keys
    if key in JSON_LIKE_KEYS:
        return _parse_json_if_needed(val)
    return val


class TextApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(APP_TITLE)
        self.minsize(APP_MIN_W, APP_MIN_H)

        # ======== GRID LAYOUT: [left | center | right] ========
        self.grid_columnconfigure(0, weight=0)  # left sidebar
        self.grid_columnconfigure(1, weight=1)  # center
        self.grid_columnconfigure(2, weight=0)  # right rail
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # ======== TOP TABS (global) ========
        self.top_tabs = TopTabs(self)
        self.top_tabs.grid(
            row=0, column=0, columnspan=3, sticky="we", padx=12, pady=(8, 0)
        )

        # ======== LEFT SIDEBAR ========
        self.left = LeftSidebar(self)
        self.left.grid(row=1, column=0, sticky="nsw", padx=(12, 6), pady=12)

        # ======== CENTER (hero + bottom prompt) ========
        self.center = CenterText(self)
        self.center.grid(row=1, column=1, sticky="nsew", padx=6, pady=12)

        # ======== RIGHT RAIL (model & features) ========
        self.rail = RightRailText(self)
        self.rail.grid(row=1, column=2, sticky="ns", padx=(6, 12), pady=12)

        # хоткеи
        self.bind_all("<Control-Return>", lambda e: self.center.on_send())
        self.bind_all("<Command-Return>", lambda e: self.center.on_send())  # macOS
        self.bind_all("<Escape>", lambda e: self.center.clear_input())


# ---------------- LEFT ----------------
class LeftSidebar(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, corner_radius=16, fg_color=("gray10", "gray12"))
        self.configure(width=220)
        self.grid_propagate(False)
        self.grid_rowconfigure(2, weight=1)

        # «Нет данных» — заглушка под список проектов/чатов
        box = ctk.CTkFrame(self, corner_radius=16, fg_color=("gray11", "gray13"))
        box.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        box.grid_propagate(False)
        box.configure(height=560)
        ctk.CTkLabel(box, text="Нет данных", text_color=("gray70", "gray60")).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        # нижние иконки (по желанию)
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="we", padx=12, pady=(6, 12))
        ctk.CTkButton(bottom, text="Новый проект", command=lambda: None).pack(fill="x")


class TopTabs(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, corner_radius=16, fg_color=("gray10", "gray12"))
        self.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        tabs = [
            ("Текст", True),
            ("Изображение", False),
            ("Дизайн", False),
            ("Видео", False),
            ("Аудио", False),
        ]
        col = 0
        for name, active in tabs:
            lab = ctk.CTkLabel(
                bar,
                text=name,
                text_color=("white" if active else "gray70"),
                font=ctk.CTkFont(size=13, weight="bold" if active else "normal"),
            )
            lab.grid(row=0, column=col, padx=(0, 16), sticky="w")
            col += 1


# ---------------- CENTER ----------------
class CenterText(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, corner_radius=16, fg_color=("gray10", "gray12"))
        self.grid_rowconfigure(0, weight=1)  # hero
        self.grid_rowconfigure(1, weight=0)  # prompt bar
        self.grid_columnconfigure(0, weight=1)

        # центральный «чистый экран» с логотипом и фразой
        hero = ctk.CTkFrame(self, corner_radius=16, fg_color=("#0f0f13", "#0f0f13"))
        hero.grid(row=0, column=0, sticky="nsew", padx=14, pady=(12, 6))
        hero.grid_rowconfigure(0, weight=1)
        hero.grid_columnconfigure(0, weight=1)

        # логотип «кольцо» простым Canvas
        cnv = tk.Canvas(hero, bg="#0f0f13", highlightthickness=0)
        cnv.grid(row=0, column=0, sticky="nsew")

        def draw():
            cnv.delete("all")
            w = cnv.winfo_width() or 800
            h = cnv.winfo_height() or 480
            cx, cy = w // 2, h // 2 - 10
            r1, r2 = 36, 20
            cnv.create_oval(
                cx - r1, cy - r1, cx + r1, cy + r1, outline="#a8a8b3", width=2
            )
            cnv.create_oval(
                cx - r2, cy - r2, cx + r2, cy + r2, outline="#a8a8b3", width=2
            )
            cnv.create_text(
                cx,
                cy + 54,
                text="Чем я могу помочь?",
                fill="#d8d8e0",
                font=("Arial", 14),
            )

        cnv.bind("<Configure>", lambda e: draw())
        self.hero_canvas = cnv

        # нижняя панель ввода
        self.prompt = PromptBar(
            self, on_send=self.on_send, on_attach=self.on_attach, on_mic=self.on_mic
        )
        self.prompt.grid(row=1, column=0, sticky="we", padx=14, pady=14)

    # ----- actions (TODO: подключение API) -----
    def on_send(self):
        text = self.prompt.get_text().strip()
        model_key = self.master.rail.model_var.get()
        input_payload = self.master.rail.get_effective_input()
        # перезапишем prompt текстом из поля, если он есть в конфиге; иначе добавим
        if text:
            if "prompt" in input_payload:
                input_payload["prompt"] = text
            else:
                input_payload["user_prompt"] = text

        # --- Показать предварительно собранный запрос ---
        try:
            import json as _json

            preview = _json.dumps(
                {"model": model_key, "input": input_payload},
                ensure_ascii=False,
                indent=2,
            )
        except Exception:
            preview = str({"model": model_key, "input": input_payload})
        mb.showinfo("Запрос (preview)", preview)

        # проверим наличие клиента replicate
        if replicate is None:
            mb.showerror(
                "Ошибка",
                "Пакет 'replicate' не установлен. Установите: pip install replicate",
            )
            return

        # читаем ключ из .env / окружения
        REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY")
        if not REPLICATE_API_KEY:
            mb.showerror(
                "Нет ключа",
                "Не найден REPLICATE_API_KEY (добавьте в .env или окружение)",
            )
            return
        client = replicate.Client(api_token=REPLICATE_API_KEY)

        def worker():
            try:
                # Создаём предикшн
                prediction = client.predictions.create(
                    model=model_key,
                    input=input_payload,
                )
                # Поллинг статуса (как в твоём примере)
                while prediction.status not in ("succeeded", "failed"):
                    print("Статус:", prediction.status)
                    time.sleep(1)
                    prediction = client.predictions.get(prediction.id)

                if prediction.status == "succeeded":
                    out = prediction.output
                    # Whisper-частный случай
                    whisper_text = _as_whisper_transcription(out)
                    if whisper_text is not None:
                        msg = whisper_text
                    else:
                        # Если список ссылок — соберём их
                        urls = []
                        if isinstance(out, list):
                            for item in out:
                                if isinstance(item, str) and item.startswith(
                                    ("http://", "https://")
                                ):
                                    urls.append(item)
                            if not urls and len(out) == 1 and isinstance(out[0], str):
                                urls = [out[0]]
                        elif isinstance(out, str) and out.startswith(
                            ("http://", "https://")
                        ):
                            urls = [out]

                        if urls:
                            msg = "\n".join(urls)
                        else:
                            # fallback
                            msg = format_prediction_output(out)
                else:
                    msg = f"Статус: {prediction.status}\nОшибка: {getattr(prediction, 'error', None)}"

            except Exception as e:
                msg = f"Исключение при запросе: {e}"

            # показать результат в главном потоке
            try:
                self.master.after(0, lambda: mb.showinfo("Ответ модели", msg))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
        # очистим поле сразу
        self.prompt.clear_input()

    def on_attach(self):
        # TODO: выбор файла
        pass

    def on_mic(self):
        # TODO: голосовой ввод
        pass

    def clear_input(self):
        self.prompt.clear_input()


class PromptBar(ctk.CTkFrame):
    def __init__(self, master, on_send, on_attach, on_mic):
        super().__init__(master, corner_radius=16, fg_color=("gray11", "gray13"))
        self.grid_columnconfigure(1, weight=1)

        self.attach_btn = ctk.CTkButton(self, text="📎", width=44, command=on_attach)
        self.attach_btn.grid(row=0, column=0, padx=(10, 6), pady=10)

        self.input = ctk.CTkEntry(self, placeholder_text="Напишите ваш промпт…")
        self.input.grid(row=0, column=1, sticky="we", pady=10)

        self.mic_btn = ctk.CTkButton(self, text="🎙", width=44, command=on_mic)
        self.mic_btn.grid(row=0, column=2, padx=6, pady=10)

        self.send_btn = ctk.CTkButton(self, text="▶", width=56, command=on_send)
        self.send_btn.grid(row=0, column=3, padx=(6, 10), pady=10)

    def get_text(self) -> str:
        return self.input.get()

    def clear_input(self):
        self.input.delete(0, "end")


# ---------------- RIGHT ----------------
class RightRailText(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, corner_radius=16, fg_color=("gray10", "gray12"))
        self.configure(width=340)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)

        # "Стоимость" шапка
        header = ctk.CTkFrame(self, fg_color=("gray11", "gray13"), corner_radius=12)
        header.grid(row=0, column=0, sticky="we", padx=12, pady=(12, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="Стоимость").grid(
            row=0, column=0, padx=10, pady=10, sticky="w"
        )
        ctk.CTkLabel(header, text="⚡ 0.00", text_color="#b8b8ff").grid(
            row=0, column=1, padx=10, pady=10, sticky="e"
        )

        # Выпадашка выбора модели
        model_block = ctk.CTkFrame(
            self, fg_color=("gray11", "gray13"), corner_radius=12
        )
        model_block.grid(row=1, column=0, sticky="we", padx=12, pady=6)
        ctk.CTkLabel(
            model_block, text="Модель", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
        self.model_var = tk.StringVar(value="openai/gpt-4o-mini")
        self._model_menu = ctk.CTkOptionMenu(
            model_block,
            variable=self.model_var,
            values=[],  # values will be loaded from JSON configs only
        )
        self._model_menu.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="we")

        # Load external model configs (JSON) and extend the models list
        self.load_models_from_dir("models_conf/text")
        # If any configs are present, select the first one by default
        try:
            vals = list(self._model_menu.cget("values"))
            if vals:
                self.model_var.set(vals[0])
        except Exception:
            pass

        # Контейнер для настроек
        self.settings_container = ctk.CTkScrollableFrame(
            self, height=420, corner_radius=12, fg_color=("gray11", "gray13")
        )
        self.settings_container.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        self.grid_rowconfigure(2, weight=1)

        self.current_vars: dict[str, tk.Variable] = {}
        self._current_cfg: dict | None = None
        self._hidden_defaults: dict[str, object] = {}

        # ----- вспомогательные элементы -----
        def _slider_row(
            parent,
            label: str,
            var: tk.DoubleVar,
            min_v: float,
            max_v: float,
            step: float,
        ):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=label).grid(
                row=0, column=0, padx=12, pady=(10, 4), sticky="w"
            )
            s = ctk.CTkSlider(
                row,
                from_=min_v,
                to=max_v,
                number_of_steps=max(1, int((max_v - min_v) / max(step, 0.001))),
                variable=var,
            )
            s.grid(row=0, column=1, padx=12, pady=(10, 4), sticky="we")
            val = ctk.CTkLabel(
                row, text=f"{float(var.get()):.2f}", text_color=("gray75", "gray60")
            )
            val.grid(row=0, column=2, padx=(0, 12), pady=(10, 4))
            var.trace_add(
                "write", lambda *_: val.configure(text=f"{float(var.get()):.2f}")
            )
            row.pack(fill="x")
            return row

        def _int_entry(parent, label: str, var: tk.StringVar, placeholder: str = "0"):
            ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=12, pady=(10, 4))
            ent = ctk.CTkEntry(parent, textvariable=var, placeholder_text=placeholder)
            ent.pack(fill="x", padx=12)
            return ent

        def _checkbox(parent, label: str, var: tk.BooleanVar):
            chk = ctk.CTkCheckBox(parent, text=label, variable=var)
            chk.pack(anchor="w", padx=12, pady=(8, 0))
            return chk

        def _text_entry(parent, label: str, var: tk.StringVar, rows: int = 2):
            ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=12, pady=(10, 4))
            if rows <= 1:
                ent = ctk.CTkEntry(parent, textvariable=var, placeholder_text="")
                ent.pack(fill="x", padx=12)
            else:
                tb = ctk.CTkTextbox(parent, height=rows * 22)
                tb.insert("1.0", var.get())
                tb.pack(fill="x", padx=12)

                def sync(*_):
                    var.set(tb.get("1.0", "end").strip())

                tb.bind("<KeyRelease>", sync)

        def _rebuild_settings(*_):
            # Build strictly from JSON config; if none, show hint
            for w in list(self.settings_container.winfo_children()):
                w.destroy()
            self.current_vars = {}
            self._hidden_defaults = {}

            mid = self.model_var.get()
            cfg = getattr(self, "_model_confs", {}).get(mid)
            self._current_cfg = cfg
            if not cfg:
                ctk.CTkLabel(
                    self.settings_container,
                    text="Нет конфига для этой модели (добавьте JSON в models_conf/text)",
                ).pack(padx=12, pady=12, anchor="w")
                return

            for c in cfg.get("controls", []):
                t = c.get("type")
                key = c.get("key")
                if not key:
                    continue

                hidden = bool(c.get("hidden", False)) or (c.get("enabled") is False)
                default = c.get("default")

                if hidden:
                    # не рисуем контрол, но запоминаем значение для итогового input
                    self._hidden_defaults[key] = default
                    continue

                # рисуем только видимые контролы
                if t == "slider":
                    var = tk.DoubleVar(value=float(c.get("default", 0.0)))
                    self.current_vars[key] = var
                    _slider_row(
                        self.settings_container,
                        key,
                        var,
                        float(c.get("min", 0.0)),
                        float(c.get("max", 1.0)),
                        float(c.get("step", 0.01)),
                    )
                elif t == "int":
                    var = tk.StringVar(value=str(c.get("default", 0)))
                    self.current_vars[key] = var
                    _int_entry(
                        self.settings_container, key, var, str(c.get("default", 0))
                    )
                elif t == "checkbox":
                    var = tk.BooleanVar(value=bool(c.get("default", False)))
                    self.current_vars[key] = var
                    _checkbox(self.settings_container, key, var)
                elif t == "select":
                    var = tk.StringVar(value=str(c.get("default", "")))
                    self.current_vars[key] = var
                    _text_entry(self.settings_container, key, var, rows=1)
                else:
                    var = tk.StringVar(value=str(c.get("default", "")))
                    self.current_vars[key] = var
                    _text_entry(self.settings_container, key, var, rows=2)

        self._model_menu.configure(command=lambda choice=None: _rebuild_settings())
        _rebuild_settings()

    def load_models_from_dir(self, dirpath: str):
        """Read all *.json model configs, register them, and extend the OptionMenu values."""
        self._model_confs = getattr(self, "_model_confs", {})
        found = {}
        for path in glob.glob(os.path.join(dirpath, "*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                continue
            mid = cfg.get("model_id")
            if not mid:
                continue
            found[mid] = cfg
        if not found:
            return
        self._model_confs.update(found)
        # Only configs from folder should be visible
        try:
            values = sorted(list(self._model_confs.keys()))
            self._model_menu.configure(values=values)
            try:
                cur = self.model_var.get()
                if cur not in values and values:
                    self.model_var.set(values[0])
            except Exception:
                pass
        except Exception:
            pass

    def build_from_config(self, cfg: dict):
        """(Optional helper) Build UI from a given config dict."""
        for w in list(self.settings_container.winfo_children()):
            w.destroy()
        self.current_vars = {}
        for c in cfg.get("controls", []):
            t = c.get("type")
            key = c.get("key")
            if not key:
                continue
            if t == "slider":
                var = tk.DoubleVar(value=float(c.get("default", 0.0)))
                self.current_vars[key] = var
                # assumes _slider_row is in scope in __init__ closure
            elif t == "int":
                var = tk.StringVar(value=str(c.get("default", 0)))
                self.current_vars[key] = var
            elif t == "checkbox":
                var = tk.BooleanVar(value=bool(c.get("default", False)))
                self.current_vars[key] = var
            else:
                var = tk.StringVar(value=str(c.get("default", "")))
                self.current_vars[key] = var

    def get_effective_input(self) -> dict:
        """Собрать словарь input из текущей модели: скрытые поля берём из JSON,
        видимые — из значений виджетов. Приводим типы под API (int/float/bool/json)."""
        result = {}
        cfg = self._current_cfg or {}
        controls = cfg.get("controls", [])

        # 1) положим дефолты (включая скрытые) с приведением типов
        for c in controls:
            k = c.get("key")
            if not k:
                continue
            ctype = (c.get("type") or "text").lower()
            default_val = c.get("default")
            result[k] = _coerce_value_by_type(ctype, k, default_val)

        # 2) перезапишем видимыми значениями
        for k, var in (self.current_vars or {}).items():
            cdesc = next((c for c in controls if c.get("key") == k), None)
            ctype = (cdesc or {}).get("type", "text").lower()
            try:
                if isinstance(var, tk.BooleanVar) or ctype == "checkbox":
                    val = bool(var.get())
                elif ctype == "slider":
                    val = float(var.get())
                elif ctype == "int":
                    sval = var.get()
                    val = int(float(sval))
                else:
                    val = var.get()
            except Exception:
                val = var.get()
            result[k] = _coerce_value_by_type(ctype, k, val)

        return result

    def collect_params(self) -> dict:
        """Собрать значения текущей панели в обычный dict."""
        out = {}
        for k, var in (self.current_vars or {}).items():
            try:
                if isinstance(var, tk.BooleanVar):
                    out[k] = bool(var.get())
                else:
                    val = var.get()
                    if isinstance(val, str) and val.isdigit():
                        out[k] = int(val)
                    else:
                        out[k] = float(val) if isinstance(var, tk.DoubleVar) else val
            except Exception:
                out[k] = var.get()
        return out


if __name__ == "__main__":
    app = TextApp()
    app.mainloop()
