# Video Censor

Desktop tool for detecting Russian and English profanity in a video and censoring the selected word intervals. Speech recognition runs locally with `faster-whisper`.

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on `PATH`
- Tk support for your Python installation
- For speech recognition: install `requirements.txt`. The first run downloads the selected Whisper model. CPU uses int8; CUDA uses float16 when available.

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

Start the application with `python app.py` or `fish run.fish`.

### Niri application menu

The included `video-censor.desktop` file launches the app through `run.fish`. Install it for the current user and refresh the desktop database if available:

```fish
mkdir -p ~/.local/share/applications
cp video-censor.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications 2>/dev/null
```

It will then be available to desktop launchers that read XDG application entries, such as Fuzzel or Wofi under Niri. Tk uses the system's available X11/Wayland compatibility layer.

### Other platforms

```sh
python -m venv .venv
source .venv/bin/activate  # POSIX sh/bash/zsh; Fish: source .venv/bin/activate.fish
python -m pip install -r requirements.txt
python app.py
```

Choose a video and output folder, select a censoring mode and padding, then press **Analyze video**. Review the detected words and uncheck false positives before pressing **Render**. A custom sound file is required for Custom Sound mode. The built-in list is in `blacklist.txt`; one word or substring mask per line. You can load another list or add entries in the app.

## Notes

- Detection uses word-level timestamps and substring matching against the built-in and user-provided terms. Short roots can match innocent words; review the results before rendering.
- Bleep, Mute, and Custom Sound preserve the original video stream where possible. Fast-Forward speeds the flagged interval up 3x; Cut removes it. These editing modes re-encode video and audio for clean joins.
- Output is MP4. The renderer tries NVENC when available and falls back to `libx264`.
- The application does not upload media. Model files are downloaded from the model registry on first use.
