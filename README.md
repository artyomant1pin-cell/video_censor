# Cut-Helper

Desktop toolkit for streamer video editing. It detects Russian and English profanity locally with `faster-whisper`, can censor selected intervals, and downloads YouTube video thumbnails with their titles.

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on `PATH`
- Tk support for your Python installation
- Install `requirements.txt` for the GUI, drag-and-drop support, and speech recognition. The PyAV and tkinterdnd2 version limits keep compatibility with faster-whisper and the Tcl 8.6 libraries provided on current Arch systems. The first run downloads the selected Whisper model. CPU uses int8; CUDA uses float16 when available, with automatic CPU fallback if CUDA libraries are missing.

On Debian/Ubuntu install the system packages with `sudo apt install ffmpeg python3-tk`. On Arch Linux use `sudo pacman -S ffmpeg tk`. On Windows, install FFmpeg and add its `bin` directory to `PATH`.

## Run

### Fish on Linux

On Arch Linux, install the system dependencies, including pip:

```fish
sudo pacman -S ffmpeg tk python python-pip
```

Create the environment and install the Python dependencies:

```fish
cd /home/future/video_censor
python3 -m venv .venv
source .venv/bin/activate.fish
python -m pip install -r requirements.txt
```

Start the application with `fish run.fish`. During analysis, recognized words are added to the results list as they arrive with exact start/end timecodes. Paste a YouTube link and press **Скачать превью** to save the thumbnail and show the video title. Use **Скачать видео** for a public YouTube/Twitch recording or live stream. Active streams continue downloading until they end or you press **Остановить**; partial data is retained for resuming. Completed renders are stored in `~/.local/share/cut-helper/history.json` and shown in the in-app history panel.

The app remembers the last normal window size and position in `~/.local/share/cut-helper/settings.json`.

For NVIDIA speech recognition, install the CUDA 12 libraries expected by CTranslate2, then launch through `run.fish` so their library paths are set:

```fish
python -m pip install -r requirements-nvidia.txt
fish run.fish
```

The CUDA libraries are installed inside `.venv`; the system CUDA installation is left alone. If CUDA initialization still fails, the app reports the reason and retries on CPU.

### Niri application menu

Install a launcher for the current user. The script finds the project directory automatically and writes the desktop entry to the XDG applications folder:

```fish
fish install.fish
```

The launcher will be available to desktop launchers that read XDG application entries, such as Fuzzel or Wofi under Niri. Tk uses the system's available X11/Wayland compatibility layer.

### Other platforms

```sh
python -m venv .venv
source .venv/bin/activate  # POSIX sh/bash/zsh; Fish: source .venv/bin/activate.fish
python -m pip install -r requirements.txt
python app.py
```

Choose a video with the file picker or drag it into the app window. Select an output folder, censoring mode, and padding, then press **Analyze video**. Review the detected words and uncheck false positives before pressing **Render**. A custom sound file is required for Custom Sound mode. In `blacklist.txt` or an imported list, plain words match whole tokens, `word*` matches tokens beginning with that form, and `*word*` explicitly searches inside a token. You can load another list or add entries in the app.

## Notes

- Detection uses word-level timestamps and exact token matching by default. Prefix and substring matching only happen when a list entry includes an explicit `*` mask.
- Bleep, Mute, and Custom Sound preserve the original video stream where possible. Fast-Forward speeds the flagged interval up 3x; Cut removes it. These editing modes re-encode video and audio for clean joins.
- Rendered audio is loudness-normalized to `-16 LUFS` with a `-1.5 dBTP` peak target. Bleep/custom-sound mixing does not attenuate the source according to the number of censored intervals. This makes quiet source recordings easier to hear while keeping peaks controlled.
- Output is MP4. The renderer tries NVENC when available and falls back to `libx264`.
- The application does not upload media. Model files are downloaded from the model registry on first use.
