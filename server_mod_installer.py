import hashlib
import json
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from constants import SERVER_LIST_MOD, SERVER_LIST_MOD_URL
from utils import sha256_file, search_bak_and_switch, next_bak_path, download_file, write_bytes_to_file


class ServerModInstaller:
    def __init__(self, coj_path: Path, log_func: Callable[[str], None]):
        self.coj_path = coj_path
        self.log_func = log_func
        self.current_files = {}

    @staticmethod
    def get_custom_servers() -> list[str] | None:
        try:
            from custom_servers import CUSTOM_SERVERS
            return CUSTOM_SERVERS
        except ModuleNotFoundError:
            return None

    async def check_files(self):
        for release_tag, release in SERVER_LIST_MOD.items():
            for file_name, file_hash in release.items():
                if file_name in self.current_files:
                    continue
                file_path = self.coj_path / file_name
                self.current_files[file_name] = (await sha256_file(file_path)) if file_path.exists() else None

    async def revert_to_version(self, release_tag: str, extra_success_info='') -> bool:
        failed_files = []
        for file_name, file_hash in SERVER_LIST_MOD[release_tag].items():
            if self.current_files[file_name] == file_hash:
                continue
            if await search_bak_and_switch(self.coj_path / file_name, file_hash):
                self.current_files[file_name] = file_hash
            else:
                failed_files.append(file_name)
        if failed_files:
            self.log_func(f'failed to revert to {release_tag}: {", ".join(failed_files)}!')
            return False
        else:
            self.log_func(f'reverted to {release_tag}{extra_success_info}!')
            return True

    async def apply(self):
        release_tag = next(iter(SERVER_LIST_MOD))
        await self.check_files()
        file_is_missing = False
        for file_name, file_hash in SERVER_LIST_MOD[release_tag].items():
            current_hash = self.current_files[file_name]
            if current_hash == file_hash:
                continue
            elif not current_hash:
                file_is_missing = True
                self.log_func(f'{file_name} missing!')
            break
        else:
            self.log_func('already patched!')
            await self.revert_to_version('steam', ' version')
            return
        if not file_is_missing:
            if await self.revert_to_version(release_tag, ' (server list mod)'):
                return
        self.log_func('checking latest release..')
        async with httpx.AsyncClient() as client:
            response = await client.get(SERVER_LIST_MOD_URL + 'releases/latest')
        try:
            response.raise_for_status()
        except httpx.HTTPError as e:
            self.log_func(str(e))
            return
        latest_release = json.loads(response.text)
        latest_release_tag = latest_release['tag_name']
        if latest_release_tag != release_tag:
            self.log_func('newer server list mod available!')
        else:
            self.log_func('getting release download url..')
        async with httpx.AsyncClient() as client:
            response = await client.get(SERVER_LIST_MOD_URL + 'releases/tags/' + release_tag)
        try:
            response.raise_for_status()
        except httpx.HTTPError as e:
            self.log_func(str(e))
            return
        release = json.loads(response.text)
        for asset in release['assets']:
            if asset['content_type'] == 'application/x-zip-compressed':
                download_url = asset['browser_download_url']
                break
        else:
            self.log_func('no zip found!')
            return
        print(latest_release_tag)
        self.log_func('downloading server list mod..')
        buf = await download_file(download_url, follow_redirects=True)
        with zipfile.ZipFile(buf) as zip_file:
            for file_name, file_hash in SERVER_LIST_MOD[release_tag].items():
                current_hash = self.current_files[file_name]
                if current_hash == file_hash:
                    continue
                file = zip_file.read(file_name)
                h = hashlib.sha256()
                h.update(file)
                file_hash_zip = h.hexdigest()
                if file_hash_zip != file_hash:
                    print(f'{file_name} hash mismatch!', file_hash_zip)
                    self.log_func(f'{file_name} hash mismatch!')
                    return
                file_path = self.coj_path / file_name
                file_bak = next_bak_path(file_path)
                file_path.rename(file_bak)
                print('writing to', file_path)
                await write_bytes_to_file(file_path, file)
                print(file_name, file_hash_zip)
            serverlist = bytearray(zip_file.read('serverlist.toml'))
            custom_servers = self.get_custom_servers()
            if custom_servers:
                ind = ' ' * 4
                servers_block = '\n' + '\n'.join(f'{ind}"{s}",' for s in custom_servers) + '\n'
                idx = serverlist.rfind(b']')
                if idx != -1:
                    serverlist[idx:idx] = servers_block.encode('utf-8')
            serverlist_path = self.coj_path / 'serverlist.toml'
            if serverlist_path.exists():
                h = hashlib.sha256()
                h.update(serverlist)
                serverlist_hash = h.hexdigest()
                if await sha256_file(serverlist_path) != serverlist_hash:
                    if not await search_bak_and_switch(serverlist_path, serverlist_hash):
                        serverlist_path.rename(next_bak_path(serverlist_path))
                        await write_bytes_to_file(serverlist_path, serverlist)
            else:
                await write_bytes_to_file(serverlist_path, serverlist)
            print(zip_file.namelist())
            self.log_func(f'patched to {release_tag} (server list mod)!')
