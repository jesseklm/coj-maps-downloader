@echo off
python -m nuitka --msvc=latest --onefile --onefile-cache-mode=cached --onefile-tempdir-spec="{PROGRAM_DIR}/.coj_maps_downloader" --windows-console-mode=disable --enable-plugin=pyside6 coj_maps_downloader.py
