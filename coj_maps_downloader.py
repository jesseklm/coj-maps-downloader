# nuitka-project: --enable-plugin=pyside6
# nuitka-project-if: {OS} == "Windows":
#     nuitka-project: --onefile-cache-mode=cached
#     nuitka-project: --onefile-tempdir-spec="{PROGRAM_DIR}/.coj_maps_downloader"
#     nuitka-project: --windows-console-mode=disable

import asyncio
import json
import sys
from pathlib import Path

import httpx
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QFileDialog, QAbstractItemView
from qasync import asyncSlot, QEventLoop

from constants import CUSTOM_MAP_SOURCES, GAME_EXES
from server_mod_installer import ServerModInstaller
from ui.main import Ui_MainWindow
from utils import find_start_folder, sha256_file, download_sha256, search_bak_and_switch, next_bak_path, \
    write_bytesio_to_file


class MainWindow(Ui_MainWindow):
    def __init__(self):
        self.tasks = set()
        self.main_window = QMainWindow()
        self.setupUi(self.main_window)
        self.pushButtonFolder.clicked.connect(self.select_folder)
        self.pushButtonFetch.clicked.connect(self.fetch_maps_clicked)
        self.pushButtonCheck.clicked.connect(self.check_maps)
        self.pushButtonUpdate.clicked.connect(self.update_maps)
        self.pushButtonServerMod.clicked.connect(self.apply_mod)
        self.push_buttons = [self.pushButtonFolder, self.pushButtonFetch, self.pushButtonCheck, self.pushButtonUpdate,
                             self.pushButtonServerMod]

        for source_name, source in CUSTOM_MAP_SOURCES.items():
            self.comboBoxSource.addItem(source_name, source)

        self.tableWidget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.headers = ['map', 'ok']
        self.clear_table()
        self.scroll_index = 0

        self.map_source = ''
        self.map_dict: dict | None = None

        self.sem = asyncio.Semaphore(6)

        self.find_start_folder()

    def show(self):
        self.main_window.show()

    def set_buttons(self, status: bool):
        for push_button in self.push_buttons:
            push_button.setEnabled(status)

    def disable_input(self):
        self.set_buttons(False)
        self.lineEditFolder.setEnabled(False)
        self.comboBoxSource.setEnabled(False)

    def enable_input(self):
        self.set_buttons(True)
        self.lineEditFolder.setEnabled(True)
        self.comboBoxSource.setEnabled(True)

    def clear_table(self):
        self.tableWidget.clear()
        self.tableWidget.setColumnCount(0)
        self.tableWidget.setRowCount(0)
        self.tableWidget.setColumnCount(len(self.headers))
        self.tableWidget.setHorizontalHeaderLabels(self.headers)

    def scroll_up(self):
        self.scroll_index = 0
        self.tableWidget.scrollToTop()

    def scroll_down_to(self, i):
        if i > self.scroll_index:
            self.scroll_index = i
            self.tableWidget.scrollTo(self.tableWidget.model().index(i, 0))

    def set_map_status(self, i: int, status: str):
        ok_index = self.headers.index('ok')
        self.tableWidget.setItem(i, ok_index, QTableWidgetItem(status))
        self.scroll_down_to(i)
        self.tableWidget.resizeColumnToContents(ok_index)

    def add_row(self, row: dict):
        row_count = self.tableWidget.rowCount()
        self.tableWidget.setRowCount(row_count + 1)
        for key, value in row.items():
            self.tableWidget.setItem(row_count, self.headers.index(key), QTableWidgetItem(str(value)))

    def find_start_folder(self) -> str:
        if not self.lineEditFolder.text():
            if start_folder := find_start_folder():
                self.lineEditFolder.setText(str(start_folder))
                return str(start_folder)
        return ''

    def get_selected_coj_folder(self) -> Path | None:
        if not self.lineEditFolder.text():
            self.statusbar.showMessage('select folder!')
            return None
        coj_path = Path(self.lineEditFolder.text())
        if coj_path.exists():
            return coj_path
        self.statusbar.showMessage('folder not found!')
        return None

    @asyncSlot()
    async def select_folder(self):
        start_folder = self.lineEditFolder.text()
        if not start_folder:
            self.find_start_folder()
        file_path, _ = QFileDialog.getOpenFileName(
            self.main_window,
            f'select CoJ:BiB – {GAME_EXES[0]}',
            start_folder,
            f'{GAME_EXES[0]} ({GAME_EXES[0]});;Executables (*.exe);;All Files (*)',
        )
        if not file_path:
            self.statusbar.showMessage('select aborted.')
            return
        exe_path = Path(file_path).resolve()
        self.lineEditFolder.setText(str(exe_path.parent))

    async def check_map_hash(self, map_file_path, map_hash, i) -> bool:
        if await sha256_file(map_file_path) == map_hash:
            self.set_map_status(i, 'ok')
            return True
        else:
            self.set_map_status(i, 'mismatch')
            return False

    async def download_map(self, i, map_file, map_hash, map_file_path):
        self.set_map_status(i, 'downloading')
        buf, h = await download_sha256(self.comboBoxSource.currentData()['maps'] + map_file)
        if h != map_hash:
            self.set_map_status(i, 'download mismatch')
            return
        self.set_map_status(i, 'writing')
        await write_bytesio_to_file(map_file_path, buf)
        self.set_map_status(i, 'ok')

    async def process_map(self, maps_path, map_file, map_hash, i, download=True):
        async with self.sem:
            map_file_path = maps_path / map_file
            if map_file_path.exists():
                if await self.check_map_hash(map_file_path, map_hash, i) or (not download):
                    return
                if await search_bak_and_switch(map_file_path, map_hash):
                    self.set_map_status(i, 'ok')
                    return
                map_file_path.rename(next_bak_path(map_file_path))
            else:
                if not download:
                    self.set_map_status(i, 'missing')
                    return
            await self.download_map(i, map_file, map_hash, map_file_path)

    def get_maps_path(self, create=False) -> Path | None:
        coj_path = self.get_selected_coj_folder()
        if not coj_path:
            return None
        coj2_path = coj_path / 'CoJ2'
        if not coj2_path.exists():
            self.statusbar.showMessage('CoJ2-folder is missing!')
            return None
        data_path = coj2_path / 'Data'
        if not data_path.exists():
            self.statusbar.showMessage('Data-folder is missing!')
            return None
        maps_path = data_path / 'MapsNet'
        if create:
            maps_path.mkdir(exist_ok=True)
        return maps_path

    async def fetch_maps(self):
        self.statusbar.showMessage('fetching map-list..')
        self.clear_table()
        async with httpx.AsyncClient() as client:
            response = await client.get(self.comboBoxSource.currentData()['manifest'])
        try:
            response.raise_for_status()
        except httpx.HTTPError as e:
            self.statusbar.showMessage(str(e))
            return
        self.map_dict = json.loads(response.text)
        self.map_source = self.comboBoxSource.currentText()
        for map_file, map_hash in self.map_dict.items():
            self.add_row({'map': map_file})
        self.tableWidget.resizeColumnsToContents()
        self.tableWidget.scrollToBottom()
        self.statusbar.showMessage('map-list fetched.')

    @asyncSlot()
    async def fetch_maps_clicked(self):
        self.disable_input()
        await self.fetch_maps()
        self.enable_input()

    @asyncSlot()
    async def check_maps(self):
        self.disable_input()
        if self.map_source != self.comboBoxSource.currentText():
            await self.fetch_maps()
        self.statusbar.showMessage('checking maps..')
        maps_path = self.get_maps_path()
        if not maps_path:
            self.enable_input()
            return
        self.scroll_up()
        async with asyncio.TaskGroup() as tg:
            for i, (map_file, map_hash) in enumerate(self.map_dict.items()):
                tg.create_task(self.process_map(maps_path, map_file, map_hash, i, download=False))
        self.tableWidget.scrollToBottom()
        self.statusbar.showMessage('maps checked!')
        self.enable_input()

    @asyncSlot()
    async def update_maps(self):
        self.disable_input()
        if self.map_source != self.comboBoxSource.currentText():
            await self.fetch_maps()
        self.statusbar.showMessage('updating maps..')
        maps_path = self.get_maps_path(create=True)
        if not maps_path:
            self.enable_input()
            return
        self.scroll_up()
        async with asyncio.TaskGroup() as tg:
            for i, (map_file, map_hash) in enumerate(self.map_dict.items()):
                tg.create_task(self.process_map(maps_path, map_file, map_hash, i))
        self.tableWidget.scrollToBottom()
        self.statusbar.showMessage('maps updated!')
        self.enable_input()

    @asyncSlot()
    async def apply_mod(self):
        self.disable_input()
        coj_path = self.get_selected_coj_folder()
        if not coj_path:
            self.enable_input()
            return
        server_mod_installer = ServerModInstaller(coj_path, lambda x: self.statusbar.showMessage(x))
        await server_mod_installer.apply()
        self.enable_input()


async def main(app):
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    main_window = MainWindow()
    main_window.show()
    await app_close_event.wait()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    asyncio.run(main(app), loop_factory=QEventLoop)
