from __future__ import annotations

import queue
import re
import threading
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from urllib.parse import urlparse

import customtkinter as ctk
from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD

from engine import CensorError, Hit, detect, load_terms, probe_media, render


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path.home() / ".local" / "share" / "cut-helper"
HISTORY_FILE = DATA_DIR / "history.json"
LEGACY_HISTORY_FILE = APP_DIR / "censor_history.json"
MODES = ["Bleep", "Mute", "Fast-Forward", "Cut", "Custom Sound"]


def timestamp(value: float) -> str:
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


class CensorApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.title("Cut-Helper")
        self.geometry("980x860")
        self.minsize(800, 700)
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        self.video = ctk.StringVar()
        self.youtube_url = ctk.StringVar()
        self.youtube_result = ctk.StringVar(value="")
        self.output_dir = ctk.StringVar(value=str(Path.home() / "Videos"))
        self.mode = ctk.StringVar(value="Bleep")
        self.sound = ctk.StringVar()
        self.padding = ctk.IntVar(value=80)
        self.model = ctk.StringVar(value="base")
        self.status = ctk.StringVar(value="Выберите видео для анализа")
        self.hits: list[Hit] = []
        self.hit_checks: list[ctk.CTkCheckBox] = []
        self.external_lists: list[Path] = []
        self.history: list[dict] = self._load_history()
        self._stream_stop = threading.Event()
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
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Cut-Helper", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, padx=22, pady=(18, 12), sticky="w")

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, padx=16, pady=4, sticky="nsew")
        censor_tab = self.tabs.add("Цензура")
        online_tab = self.tabs.add("YouTube и Twitch")
        history_tab = self.tabs.add("История")
        for tab in (censor_tab, online_tab, history_tab):
            tab.grid_columnconfigure(0, weight=1)
        censor_tab.grid_rowconfigure(3, weight=1)
        history_tab.grid_rowconfigure(0, weight=1)

        source = ctk.CTkFrame(censor_tab, fg_color="transparent")
        source.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        source.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(source, text="Видео").grid(row=0, column=0, padx=(4, 10))
        ctk.CTkEntry(source, textvariable=self.video).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(source, text="Выбрать…", width=112, command=self._choose_video).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkLabel(source, text="Папка результата").grid(row=1, column=0, padx=(4, 10), pady=(8, 0))
        ctk.CTkEntry(source, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ctk.CTkButton(source, text="Обзор…", width=112, command=self._choose_dir).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))
        self.drop_hint = ctk.CTkLabel(source, text="Подключение drag-and-drop…", text_color=("gray45", "gray65"), anchor="w")
        self.drop_hint.grid(row=2, column=1, sticky="w", pady=(4, 0))

        settings = ctk.CTkFrame(censor_tab)
        settings.grid(row=1, column=0, padx=4, pady=10, sticky="ew")
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

        toolbar = ctk.CTkFrame(censor_tab, fg_color="transparent")
        toolbar.grid(row=2, column=0, padx=4, pady=(0, 7), sticky="ew")
        self.analyze_button = ctk.CTkButton(toolbar, text="Анализировать видео", command=self._analyze)
        self.analyze_button.pack(side="left")
        self.render_button = ctk.CTkButton(toolbar, text="Рендер", command=self._render, state="disabled")
        self.render_button.pack(side="left", padx=8)
        ctk.CTkButton(toolbar, text="Загрузить blacklist…", width=158, command=self._load_blacklist).pack(side="right")
        ctk.CTkButton(toolbar, text="+ Слово", width=90, command=self._add_word).pack(side="right", padx=8)

        self.results = ctk.CTkScrollableFrame(censor_tab, label_text="Найденные слова · снимите отметку с ложных срабатываний")
        self.results.grid(row=3, column=0, padx=4, pady=4, sticky="nsew")
        self.results.grid_columnconfigure(0, weight=1)

        youtube = ctk.CTkFrame(online_tab)
        youtube.grid(row=0, column=0, padx=10, pady=10, sticky="new")
        youtube.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(youtube, text="YouTube").grid(row=0, column=0, padx=(12, 8), pady=9)
        ctk.CTkEntry(youtube, textvariable=self.youtube_url, placeholder_text="Вставьте ссылку на ролик").grid(row=0, column=1, padx=4, sticky="ew")
        self.youtube_button = ctk.CTkButton(youtube, text="Скачать превью", width=140, command=self._download_youtube_thumbnail)
        self.youtube_button.grid(row=0, column=2, padx=(8, 12))
        self.youtube_result_label = ctk.CTkLabel(youtube, textvariable=self.youtube_result, anchor="w", justify="left")
        self.youtube_result_label.grid(row=1, column=1, padx=4, pady=(0, 8), sticky="ew")
        self.open_thumbnail_button = ctk.CTkButton(youtube, text="Открыть", width=90, state="disabled")
        self.open_thumbnail_button.grid(row=1, column=2, padx=(8, 12), pady=(0, 8))
        ctk.CTkLabel(youtube, text="Стрим / запись").grid(row=2, column=0, padx=(12, 8), pady=(2, 8))
        ctk.CTkEntry(youtube, textvariable=self.youtube_url, placeholder_text="Ссылка YouTube или Twitch").grid(row=2, column=1, padx=4, pady=(2, 8), sticky="ew")
        self.stream_button = ctk.CTkButton(youtube, text="Скачать видео", width=140, command=self._download_stream)
        self.stream_button.grid(row=2, column=2, padx=(8, 12), pady=(2, 8))
        self.stop_stream_button = ctk.CTkButton(youtube, text="Остановить", width=90, state="disabled", command=self._stop_stream)
        self.stop_stream_button.grid(row=3, column=2, padx=(8, 12), pady=(0, 8))
        self.stream_progress = ctk.CTkProgressBar(youtube)
        self.stream_progress.grid(row=3, column=1, padx=4, pady=(0, 8), sticky="ew")
        self.stream_progress.set(0)
        self.stream_status = ctk.CTkLabel(youtube, text="", anchor="w")
        self.stream_status.grid(row=4, column=1, padx=4, pady=(0, 8), sticky="ew")

        self.history_frame = ctk.CTkScrollableFrame(history_tab, label_text="Зацензуренные видео")
        self.history_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._show_history()
        self.progress = ctk.CTkProgressBar(self)
        self.progress.grid(row=2, column=0, padx=22, pady=(10, 3), sticky="ew")
        self.progress.set(0)
        ctk.CTkLabel(self, textvariable=self.status, anchor="w").grid(row=3, column=0, padx=22, pady=(2, 12), sticky="ew")

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

    def _download_youtube_thumbnail(self):
        url = self.youtube_url.get().strip()
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in ("http", "https") or host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com"}:
            messagebox.showerror("Неверная ссылка", "Вставьте ссылку на видео YouTube.")
            return
        self.youtube_button.configure(state="disabled")
        self.open_thumbnail_button.configure(state="disabled")
        self.youtube_result.set("Получаю название и скачиваю превью…")

        def worker():
            try:
                from yt_dlp import YoutubeDL
                preview_dir = Path(self.output_dir.get()).expanduser() / "YouTube previews"
                preview_dir.mkdir(parents=True, exist_ok=True)
                template = str(preview_dir / "%(title).150B [%(id)s].%(ext)s")
                options = {
                    "skip_download": True,
                    "writethumbnail": True,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "outtmpl": {"default": template, "thumbnail": template},
                }
                with YoutubeDL(options) as downloader:
                    info = downloader.extract_info(url, download=True)
                video_id = info.get("id", "")
                files = [item for item in preview_dir.iterdir()
                         if item.is_file() and f"[{video_id}]" in item.stem]
                if not files:
                    raise RuntimeError("YouTube не предоставил файл превью для этой ссылки.")
                thumbnail = max(files, key=lambda item: item.stat().st_mtime)
                self.events.put(("youtube_done", (info.get("title", "Видео YouTube"), str(thumbnail))))
            except Exception as exc:
                self.events.put(("youtube_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _download_stream(self):
        url = self.youtube_url.get().strip()
        host = (urlparse(url).hostname or "").casefold()
        youtube_hosts = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
        twitch_hosts = {"twitch.tv", "www.twitch.tv", "m.twitch.tv", "clips.twitch.tv"}
        if urlparse(url).scheme not in ("http", "https") or host not in youtube_hosts | twitch_hosts:
            messagebox.showerror("Неверная ссылка", "Вставьте ссылку на публичный стрим или запись YouTube/Twitch.")
            return
        output_dir = Path(self.output_dir.get()).expanduser()
        if not output_dir.is_dir():
            messagebox.showerror("Папка не найдена", "Выберите существующую папку результата.")
            return
        self._stream_stop.clear()
        self.stream_button.configure(state="disabled")
        self.stop_stream_button.configure(state="normal")
        self.stream_progress.set(0)
        self.stream_status.configure(text="Подключение к потоку…")

        def worker():
            try:
                from yt_dlp import YoutubeDL
                from yt_dlp.utils import DownloadError
                template = str(output_dir / "%(title).150B [%(id)s].%(ext)s")

                def report(data):
                    if self._stream_stop.is_set():
                        raise DownloadError("Остановлено пользователем")
                    state = data.get("status")
                    if state == "downloading":
                        downloaded = data.get("downloaded_bytes", 0)
                        total = data.get("total_bytes") or data.get("total_bytes_estimate")
                        speed = data.get("speed")
                        eta = data.get("eta")
                        percent = downloaded / total if total else None
                        self.events.put(("stream_progress", (percent, speed, eta, downloaded)))
                    elif state == "finished":
                        self.events.put(("stream_status", "Загрузка получена; объединяю аудио и видео…"))

                options = {
                    "format": "bestvideo*+bestaudio/best",
                    "outtmpl": template,
                    "merge_output_format": "mp4",
                    "noplaylist": True,
                    "live_from_start": True,
                    "continuedl": True,
                    "progress_hooks": [report],
                    "quiet": True,
                    "no_warnings": True,
                }
                with YoutubeDL(options) as downloader:
                    info = downloader.extract_info(url, download=True)
                video_id = str(info.get("id", ""))
                files = [item for item in output_dir.iterdir()
                         if item.is_file() and f"[{video_id}]" in item.stem
                         and not item.name.endswith((".part", ".ytdl"))]
                if not files:
                    raise RuntimeError("Загрузка завершилась, но итоговый видеофайл не найден.")
                result = max(files, key=lambda item: item.stat().st_mtime)
                self.events.put(("stream_done", (info.get("title", "Стрим"), str(result))))
            except Exception as exc:
                if self._stream_stop.is_set():
                    self.events.put(("stream_stopped", str(exc)))
                else:
                    self.events.put(("stream_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_stream(self):
        self._stream_stop.set()
        self.stream_status.configure(text="Останавливаю загрузку; временный файл сохранится для продолжения…")

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

    def _load_history(self):
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            try:
                data = json.loads(LEGACY_HISTORY_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except (OSError, json.JSONDecodeError):
                return []

    def _show_history(self):
        for child in self.history_frame.winfo_children():
            child.destroy()
        if not self.history:
            ctk.CTkLabel(self.history_frame, text="Готовые видео появятся здесь.", anchor="w").grid(row=0, column=0, padx=10, pady=5, sticky="w")
            return
        for row, record in enumerate(self.history[:20]):
            result = Path(record.get("result", ""))
            source = Path(record.get("source", ""))
            label = f"{record.get('created', '')} · {record.get('mode', '')} · {source.name or 'исходник'} → {result.name or 'файл удалён'}"
            ctk.CTkLabel(self.history_frame, text=label, anchor="w").grid(row=row, column=0, padx=8, pady=3, sticky="w")
            ctk.CTkButton(self.history_frame, text="Видео", width=72,
                          state="normal" if result.is_file() else "disabled",
                          command=lambda path=result: self._open_path(path)).grid(row=row, column=1, padx=4, pady=2)

    def _open_path(self, path: Path):
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл: {exc}")

    def _save_history(self, source: Path, destination: Path):
        record = {
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": str(source), "result": str(destination), "mode": self.mode.get(),
            "words": [{"word": hit.word, "start": hit.start, "end": hit.end} for hit in self.hits if hit.enabled],
        }
        self.history = [record] + [item for item in self.history if item.get("result") != str(destination)]
        self.history = self.history[:50]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = HISTORY_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(HISTORY_FILE)
        self._show_history()

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
                    self.status.set(f"Найден мат: {payload.word} · {timestamp(payload.start)}–{timestamp(payload.end)}")
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
                    try:
                        self._save_history(Path(self.video.get()).expanduser(), Path(payload))
                    except OSError as exc:
                        self.status.set(f"Видео готово, но историю не удалось сохранить: {exc}")
                    self.progress.set(1)
                    if "историю не удалось сохранить" not in self.status.get():
                        self.status.set(f"Готово: {payload}")
                    self.analyze_button.configure(state="normal")
                    messagebox.showinfo("Готово", f"Файл сохранён:\n{payload}")
                elif event == "youtube_done":
                    title, path = payload
                    self.youtube_result.set(f"{title}\n{path}")
                    self.open_thumbnail_button.configure(state="normal", command=lambda p=Path(path): self._open_path(p))
                    self.youtube_button.configure(state="normal")
                    self.status.set(f"Превью скачано: {Path(path).name}")
                elif event == "youtube_error":
                    self.youtube_result.set("")
                    self.youtube_button.configure(state="normal")
                    messagebox.showerror("Ошибка YouTube", payload)
                elif event == "stream_progress":
                    percent, speed, eta, downloaded = payload
                    if percent is not None:
                        self.stream_progress.set(min(1.0, max(0.0, percent)))
                        progress_text = f"{percent * 100:.1f}%"
                    else:
                        self.stream_progress.set(0.08 if self.stream_progress.get() < 0.08 else self.stream_progress.get())
                        progress_text = "live"
                    speed_text = f" · {speed / 1024 / 1024:.1f} МБ/с" if speed else ""
                    eta_text = f" · осталось {int(eta)} с" if eta is not None else ""
                    self.stream_status.configure(text=f"{progress_text}{speed_text}{eta_text} · получено {downloaded / 1024 / 1024:.1f} МБ")
                elif event == "stream_status":
                    self.stream_status.configure(text=payload)
                elif event == "stream_done":
                    title, path = payload
                    self.stream_status.configure(text=f"Готово: {title} · {path}")
                    self.stream_progress.set(1)
                    self.stream_button.configure(state="normal")
                    self.stop_stream_button.configure(state="disabled")
                    self._set_video(path)
                elif event == "stream_stopped":
                    self.stream_status.configure(text="Загрузка остановлена; временные данные сохранены.")
                    self.stream_progress.set(0)
                    self.stream_button.configure(state="normal")
                    self.stop_stream_button.configure(state="disabled")
                elif event == "stream_error":
                    self.stream_status.configure(text="Ошибка загрузки")
                    self.stream_button.configure(state="normal")
                    self.stop_stream_button.configure(state="disabled")
                    messagebox.showerror("Ошибка загрузки", payload)
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
