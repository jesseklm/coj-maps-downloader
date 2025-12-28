import asyncio
import hashlib
import sys
from io import BytesIO
from pathlib import Path

import anyio
import httpx

from constants import LINUX_PATH, GAME_EXES, WINDOWS_REG_KEYS


def sha256_sync(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


async def sha256_file(path: Path) -> str:
    return await asyncio.to_thread(sha256_sync, path)


async def download_file(url: str, follow_redirects=False) -> BytesIO:
    buf = BytesIO()
    async with httpx.AsyncClient(follow_redirects=follow_redirects) as client:
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(1024 * 1024):
                buf.write(chunk)
    buf.seek(0)
    return buf


async def download_sha256(url: str, follow_redirects=False) -> tuple[BytesIO, str]:
    h = hashlib.sha256()
    buf = BytesIO()
    async with httpx.AsyncClient(follow_redirects=follow_redirects) as client:
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(1024 * 1024):
                buf.write(chunk)
                h.update(chunk)
    buf.seek(0)
    return buf, h.hexdigest()


async def write_bytesio_to_file(path: Path, buf: BytesIO, *, chunk_size=1024 * 1024):
    view = buf.getbuffer()
    async with await anyio.open_file(path, 'wb') as f:
        for offset in range(0, len(view), chunk_size):
            await f.write(view[offset:offset + chunk_size])


async def write_bytes_to_file(path: Path, data: bytes | bytearray, *, chunk_size=1024 * 1024):
    view = memoryview(data)
    async with await anyio.open_file(path, 'wb') as f:
        for offset in range(0, len(view), chunk_size):
            await f.write(view[offset:offset + chunk_size])


def next_bak_path(path):
    base = path.with_name(path.name + '.bak')
    if not base.exists():
        return base
    n = 1
    while True:
        candidate = base.with_name(base.name + str(n))
        if not candidate.exists():
            return candidate
        n += 1


async def search_bak_and_switch(file_path: Path, file_hash: str):
    bak_files = list(file_path.parent.glob(file_path.name + '.bak*'))
    for bak_file in bak_files:
        if await sha256_file(bak_file) != file_hash:
            continue
        old_file = bak_file.with_name(bak_file.name + '.ren')
        file_path.rename(old_file)
        bak_file.rename(file_path)
        old_file.rename(bak_file)
        return True
    return False


def find_start_folder() -> Path | None:
    if sys.platform.startswith('linux'):
        linux_folder = Path.home() / LINUX_PATH
        for game_exe in GAME_EXES:
            if (linux_folder / game_exe).exists():
                return linux_folder.resolve()
    elif sys.platform == 'win32':
        import winreg
        for wow_flag in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for reg_path, reg_name in WINDOWS_REG_KEYS:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path,
                                        access=winreg.KEY_READ | wow_flag) as key:
                        value, reg_type = winreg.QueryValueEx(key, reg_name)
                except Exception:
                    continue
                windows_folder = Path(value)
                for game_exe in GAME_EXES:
                    if (windows_folder / game_exe).exists():
                        return windows_folder.resolve()
    return None
