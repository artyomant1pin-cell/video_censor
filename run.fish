#!/usr/bin/env fish

set -l app_dir (dirname (status filename))
cd $app_dir
or exit 1

if test -x .venv/bin/python
    exec .venv/bin/python app.py
else if command -q python3
    exec python3 app.py
else
    echo "Python 3 was not found. Install Python 3.10 or newer." >&2
    exit 1
end
