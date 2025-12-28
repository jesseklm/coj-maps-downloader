CUSTOM_MAP_SOURCES = {
    'AlfredoAnonym/CoJ-BiB-CustomMaps': {
        'manifest': 'https://raw.githubusercontent.com/AlfredoAnonym/CoJ-BiB-CustomMaps/refs/heads/main/manifest.json',
        'maps': 'https://raw.githubusercontent.com/AlfredoAnonym/CoJ-BiB-CustomMaps/refs/heads/main/CoJ2/Data/MapsNet/'
    },
    'roozbehghazavi/coj2-maps-irancoj': {
        'manifest': 'https://raw.githubusercontent.com/roozbehghazavi/coj2-maps-irancoj/refs/heads/main/manifest.json',
        'maps': 'https://raw.githubusercontent.com/roozbehghazavi/coj2-maps-irancoj/refs/heads/main/MapsNet/'
    }
}
LINUX_PATH = '.steam/steam/steamapps/common/Call of Juarez - Bound in Blood/'
WINDOWS_REG_KEYS = ((r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 21980', 'InstallLocation'),
                    (r'SOFTWARE\Techland\CallofJuarez2', 'DestinationDir'),
                    (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CoJ_BiB_DedicatedServer_is1',
                     'InstallLocation'),)
GAME_EXES = ('CoJBiBGame_x86.exe', 'CoJ2Game_x86_ds.exe')
SERVER_LIST_MOD_URL = 'https://api.github.com/repos/AlfredoAnonym/COJ-BiB-Server-List-Mod/'
SERVER_LIST_MOD = {
    'release-02122025': {
        'CoJ2_x86.dll': '3d171f7f484a7ea5ddc7a9748ffcf302a11efe1f8ceea500c1dbe38e994bfc0c',  # steam file
        'engine_x86.dll': '10ef15b83874f46f27dcb8342dce77a4a453503fd61603e2ca21522d74c3835f',
        'serverlist.dll': 'ed148cbb598aacc4a1321d0e7361aa48de1e4ae4c2cb47147f3574508e2c4ac6',
    },
    'steam': {
        'CoJ2_x86.dll': '3d171f7f484a7ea5ddc7a9748ffcf302a11efe1f8ceea500c1dbe38e994bfc0c',
        'engine_x86.dll': 'b422ff5a4f0badf7bdcbf10224bcf5d7f90b8a2edafe3efb36341853a73c14e0',
    }
}
