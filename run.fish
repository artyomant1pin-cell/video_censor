#!/usr/bin/env fish

set -l app_dir (dirname (status filename))
cd $app_dir
or exit 1

if test -x .venv/bin/python
    set -l site_packages (.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
    set -l cuda_lib_dirs
    for cuda_lib in $site_packages/nvidia/*/lib
        if test -d "$cuda_lib"
            set -a cuda_lib_dirs "$cuda_lib"
        end
    end
    if set -q cuda_lib_dirs[1]
        set -l cuda_lib_path (string join : -- $cuda_lib_dirs)
        if set -q LD_LIBRARY_PATH
            set -gx LD_LIBRARY_PATH "$cuda_lib_path:$LD_LIBRARY_PATH"
        else
            set -gx LD_LIBRARY_PATH "$cuda_lib_path"
        end
    end
    exec .venv/bin/python app.py
else if command -q python3
    exec python3 app.py
else
    echo "Python 3 was not found. Install Python 3.10 or newer." >&2
    exit 1
end
