#!/usr/bin/env fish

set -l app_dir (cd (dirname (status filename)); and pwd)
or exit 1

set -l applications_dir "$HOME/.local/share/applications"
set -l desktop_file "$applications_dir/video-censor.desktop"

mkdir -p $applications_dir
or begin
    echo "Could not create $applications_dir" >&2
    exit 1
end

# Quote the executable path for the Desktop Entry Exec field.
set -l escaped_app_dir (string replace -a '\\' '\\\\' -- $app_dir)
set escaped_app_dir (string replace -a '"' '\\"' -- $escaped_app_dir)
printf '%s\n' \
    '[Desktop Entry]' \
    'Version=1.0' \
    'Type=Application' \
    'Name=Video Censor' \
    'Comment=Detect and censor profanity in video' \
    "Exec=fish \"$escaped_app_dir/run.fish\"" \
    "Path=$app_dir" \
    'Terminal=false' \
    'Categories=AudioVideo;Video;Utility;' \
    'StartupNotify=true' > $desktop_file
or begin
    echo "Could not write $desktop_file" >&2
    exit 1
end

if command -q update-desktop-database
    update-desktop-database $applications_dir 2>/dev/null
end

echo "Installed Video Censor launcher: $desktop_file"
