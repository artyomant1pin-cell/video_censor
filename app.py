from __future__ import annotations

import queue
import re
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD

from engine import CensorError, Hit, detect, load_terms, probe_media, render


APP_DIR = Path(__file__).resolve().parent
MODES = ["Bleep", "Mute", "Fast-Forward", "Cut", "Custom Sound"]


def timestamp(value: float) -> str:
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


class CensorApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.title("Video Censor")
        self.geometry("940x760")
        self.minsize(780, 620)
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.video = ctk.StringVar()
        self.output_dir = ctk.StringVar(value=str(Path.home() / "Videos"))
        self.mode = ctk.StringVar(value="Bleep")
        self.sound = ctk.StringVar()
        self.padding = ctk.IntVar(value=80)
        self.model = ctk.StringVar(value="base")
        self.status = ctk.StringVar(value="Выберите видео для анализа")
        self.hits: list[Hit] = []
        self.hit_checks: list[ctk.CTkCheckBox] = []
        self.external_lists: list[Path] = []
        self.events: queue.Queue = queue.Queue()
        self._build()
        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._drop_video)
            self.drop_hint.configure(text="Можно перетащить видеофайл в окно")
        except (RuntimeError, ctk.TclError) as exc:
            self.status.set(f"Drag-and-drop недоступен: {exc}. Выберите видео кнопкой.")
        self.after(100, self._poll)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(self, text="Video Censor", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, padx=22, pady=(18, 12), sticky="w")

        source = ctk.CTkFrame(self, fg_color="transparent")
        source.grid(row=1, column=0, padx=18, pady=4, sticky="ew")
        source.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(source, text="Видео").grid(row=0, column=0, padx=(4, 10))
        ctk.CTkEntry(source, textvariable=self.video).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(source, text="Выбрать…", width=112, command=self._choose_video).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkLabel(source, text="Папка результата").grid(row=1, column=0, padx=(4, 10), pady=(8, 0))
        ctk.CTkEntry(source, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ctk.CTkButton(source, text="Обзор…", width=112, command=self._choose_dir).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))
        self.drop_hint = ctk.CTkLabel(source, text="Подключение drag-and-drop…", text_color=("gray45", "gray65"), anchor="w")
        self.drop_hint.grid(row=2, column=1, sticky="w", pady=(4, 0))

        settings = ctk.CTkFrame(self)
        settings.grid(row=2, column=0, padx=18, pady=10, sticky="ew")
        settings.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(settings, text="Режим").grid(row=0, column=0, padx=(12, 6), pady=12)
        ctk.CTkOptionMenu(settings, values=MODES, variable=self.mode, width=150, command=self._mode_changed).grid(row=0, column=1, padx=6, pady=12)
        ctk.CTkLabel(settings, text="Модель").grid(row=0, column=2, padx=(12, 6), pady=12)
        ctk.CTkOptionMenu(settings, values=["base", "small"], variable=self.model, width=100).grid(row=0, column=3, padx=6, pady=12, sticky="w")
        ctk.CTkLabel(settings, text="Запас").grid(row=1, column=0, padx=(12, 6), pady=(0, 12))
        self.padding_slider = ctk.CTkSlider(settings, from_=0, to=300, number_of_steps=30, variable=self.padding, command=self._padding_changed)
        self.padding_slider.grid(row=1, column=1, sticky="ew", padx=6, pady=(0, 12))
        self.padding_label = ctk.CTkLabel(settings, text="80 мс", width=60)
        self.padding_label.grid(row=1, column=2, padx=6, pady=(0, 12))
        self.sound_entry = ctk.CTkEntry(settings, textvariable=self.sound, placeholder_text="Звук для режима Custom Sound")
        self.sound_entry.grid(row=2, column=0, columnspan=3, padx=(12, 6), pady=(0, 12), sticky="ew")
        self.sound_button = ctk.CTkButton(settings, text="Файл звука…", width=112, command=self._choose_sound)
        self.sound_button.grid(row=2, column=3, padx=6, pady=(0, 12), sticky="w")
        self._mode_changed(self.mode.get())

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=3, column=0, padx=18, pady=(0, 7), sticky="ew")
        self.analyze_button = ctk.CTkButton(toolbar, text="Анализировать видео", command=self._analyze)
        self.analyze_button.pack(side="left")
        self.render_button = ctk.CTkButton(toolbar, text="Рендер", command=self._render, state="disabled")
        self.render_button.pack(side="left", padx=8)
        ctk.CTkButton(toolbar, text="Загрузить blacklist…", width=158, command=self._load_blacklist).pack(side="right")
        ctk.CTkButton(toolbar, text="+ Слово", width=90, command=self._add_word).pack(side="right", padx=8)

        self.results = ctk.CTkScrollableFrame(self, label_text="Найденные слова · снимите отметку с ложных срабатываний")
        self.results.grid(row=4, column=0, padx=18, pady=4, sticky="nsew")
        self.results.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(self)
        self.progress.grid(row=5, column=0, padx=22, pady=(10, 3), sticky="ew")
        self.progress.set(0)
        ctk.CTkLabel(self, textvariable=self.status, anchor="w").grid(row=6, column=0, padx=22, pady=(2, 12), sticky="ew")

    def _choose_video(self):
        name = filedialog.askopenfilename(title="Выберите видео", filetypes=[("Видео", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("Все файлы", "*.*")])
        if name:
            self._set_video(name)

    def _drop_video(self, event):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        if not paths:
            return REFUSE_DROP
        path = Path(paths[0]).expanduser()
        supported = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
        if not path.is_file() or path.suffix.casefold() not in supported:
            messagebox.showerror("Неподдерживаемый файл", "Перетащите видео в формате MP4, MKV, MOV, AVI, WebM или M4V.")
            return REFUSE_DROP
        self._set_video(str(path))
        return COPY

    def _set_video(self, name):
        self.video.set(name)
        self.hits = []
        self._show_hits()
        self.render_button.configure(state="disabled")
        self.status.set(f"Выбрано видео: {Path(name).name}")

    def _choose_dir(self):
        name = filedialog.askdirectory(title="Папка результата", initialdir=self.output_dir.get() or str(Path.home()))
        if name:
            self.output_dir.set(name)

    def _choose_sound(self):
        name = filedialog.askopenfilename(title="Выберите звук", filetypes=[("Аудио", "*.wav *.mp3 *.ogg *.flac *.m4a"), ("Все файлы", "*.*")])
        if name:
            self.sound.set(name)

    def _mode_changed(self, _value=None):
        enabled = self.mode.get() == "Custom Sound"
        self.sound_entry.configure(state="normal" if enabled else "disabled")
        self.sound_button.configure(state="normal" if enabled else "disabled")

    def _padding_changed(self, value):
        self.padding_label.configure(text=f"{int(value)} мс")

    def _load_blacklist(self):
        name = filedialog.askopenfilename(title="Загрузить список слов", filetypes=[("Текст", "*.txt"), ("Все файлы", "*.*")])
        if name:
            self.external_lists.append(Path(name))
            self.status.set(f"Добавлен список: {Path(name).name}")

    def _add_word(self):
        word = simpledialog.askstring("Добавить слово", "Слово или маска для поиска:", parent=self)
        if word and word.strip():
            try:
                with (APP_DIR / "blacklist.txt").open("a", encoding="utf-8") as file:
                    file.write("\n" + word.strip())
                self.status.set(f"Добавлено в blacklist.txt: {word.strip()}")
            except OSError as exc:
                messagebox.showerror("Ошибка", f"Не удалось сохранить слово: {exc}")

    def _analyze(self):
        path = Path(self.video.get()).expanduser()
        if not path.is_file():
            messagebox.showerror("Ошибка", "Выберите существующий видеофайл.")
            return
        self.analyze_button.configure(state="disabled")
        self.render_button.configure(state="disabled")
        self.hits = []
        self._show_hits()
        self.progress.set(0.08)
        self.status.set("Подготовка анализа…")
        def worker():
            try:
                probe_media(path)
                terms = load_terms([APP_DIR / "blacklist.txt", *self.external_lists])
                hits = detect(
                    path, terms, self.model.get(),
                    lambda text: self.events.put(("status", text)),
                    lambda hit: self.events.put(("hit", hit)),
                    lambda current, total: self.events.put(("transcription_progress", (current, total))),
                )
                self.events.put(("analyzed", hits))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _render(self):
        source = Path(self.video.get()).expanduser()
        selected = [hit for hit in self.hits if hit.enabled]
        if not selected:
            messagebox.showinfo("Нет выбранных слов", "Отметьте хотя бы одно найденное слово.")
            return
        output_dir = Path(self.output_dir.get()).expanduser()
        destination = output_dir / f"{source.stem}_censored.mp4"
        custom = Path(self.sound.get()).expanduser() if self.sound.get() else None
        self.render_button.configure(state="disabled")
        self.analyze_button.configure(state="disabled")
        self.progress.set(0.56)
        def worker():
            try:
                render(source, destination, selected, self.mode.get(), int(self.padding.get()), custom,
                       lambda text: self.events.put(("status", text)))
                self.events.put(("rendered", str(destination)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _show_hits(self):
        for child in self.results.winfo_children():
            child.destroy()
        self.hit_checks.clear()
        if not self.hits:
            ctk.CTkLabel(self.results, text="Результаты анализа появятся здесь.", anchor="w").grid(row=0, column=0, padx=10, pady=8, sticky="ew")
        for index, hit in enumerate(self.hits):
            self._add_hit_row(index, hit)
        self.status.set(f"Найдено слов: {len(self.hits)}")

    def _add_hit_row(self, index, hit):
        variable = ctk.BooleanVar(value=hit.enabled)
        checkbox = ctk.CTkCheckBox(
            self.results,
            text=f"{timestamp(hit.start)}  {hit.word}  ({hit.end - hit.start:.2f} с)",
            variable=variable,
            command=lambda i=index, v=variable: self._toggle_hit(i, v.get()),
        )
        checkbox.grid(row=index, column=0, padx=10, pady=4, sticky="w")
        self.hit_checks.append(checkbox)

    def _append_live_hit(self, hit):
        if any(old.word.casefold() == hit.word.casefold() and abs(old.start - hit.start) < 0.12
               for old in self.hits):
            return
        if not self.hits:
            for child in self.results.winfo_children():
                child.destroy()
        self.hits.append(hit)
        self._add_hit_row(len(self.hits) - 1, hit)
        self.status.set(f"Распознано слов: {len(self.hits)}")

    def _toggle_hit(self, index, enabled):
        self.hits[index].enabled = enabled

    def _poll(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    self.status.set(payload)
                    if "Извлечение аудио" in payload:
                        self.progress.set(0.15)
                    elif "Транскрибация" in payload:
                        self.progress.set(0.27)
                    elif "GPU недоступна" in payload:
                        self.progress.set(0.27)
                    elif "таймкодов" in payload:
                        self.progress.set(0.58)
                    elif "Рендеринг" in payload:
                        match = re.search(r"(\d+)%", payload)
                        self.progress.set(0.58 + 0.41 * int(match.group(1)) / 100 if match else 0.6)
                elif event == "hit":
                    self._append_live_hit(payload)
                elif event == "transcription_progress":
                    current, total = payload
                    fraction = min(1.0, current / total) if total else 0.0
                    self.progress.set(0.27 + 0.3 * fraction)
                    self.status.set(f"Транскрибация: {timestamp(current)} / {timestamp(total)} · найдено {len(self.hits)}")
                elif event == "analyzed":
                    disabled = [(hit.word.casefold(), hit.start) for hit in self.hits if not hit.enabled]
                    self.hits = payload
                    for hit in self.hits:
                        if any(word == hit.word.casefold() and abs(start - hit.start) < 0.12
                               for word, start in disabled):
                            hit.enabled = False
                    self._show_hits()
                    self.progress.set(1)
                    self.analyze_button.configure(state="normal")
                    self.render_button.configure(state="normal" if payload else "disabled")
                elif event == "rendered":
                    self.progress.set(1)
                    self.status.set(f"Готово: {payload}")
                    self.analyze_button.configure(state="normal")
                    messagebox.showinfo("Готово", f"Файл сохранён:\n{payload}")
                elif event == "error":
                    self.progress.set(0)
                    self.status.set("Ошибка")
                    self.analyze_button.configure(state="normal")
                    self.render_button.configure(state="normal" if self.hits else "disabled")
                    messagebox.showerror("Ошибка", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)


if __name__ == "__main__":
    CensorApp().mainloop()
