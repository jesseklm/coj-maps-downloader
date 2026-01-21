import asyncio
import sys
import tomllib
from typing import Coroutine

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTableWidgetItem, QAbstractItemView, QWidget, QVBoxLayout, QTableWidget
from qasync import QApplication, QEventLoop

from server_list import coj_bib_lan_query
from utils import find_start_folder


class ServerWidget(QWidget):
    def __init__(self, start_folder):
        super().__init__()

        if not start_folder:
            start_folder = find_start_folder()
        self.start_folder = start_folder

        self.layout = QVBoxLayout()
        self.table = QTableWidget()
        self.layout.addWidget(self.table)
        self.setLayout(self.layout)
        self.resize(750, 500)
        self.setWindowTitle('Server List')

        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.headers = ['ip:port', 'status', 'server_name', 'map_name', 'players', 'map_file']
        self.clear_table()

        self.background_tasks = set()

    def run_in_background(self, coro: Coroutine):
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def test_server(self, server: str):
        row_num = self.add_row({'ip:port': server})
        host, port = server.rsplit(':', maxsplit=1)
        port = int(port)
        server_info = await coj_bib_lan_query(host, port)
        print(server_info)
        if 'error' in server_info:
            self.set_row(row_num, {'status': 'down'})
            return
        server_info.pop('host')
        server_info.pop('port')
        current_players = server_info.pop('current_players')
        max_players = server_info.pop('max_players')
        server_info['players'] = f'{current_players} / {max_players}'
        server_info['status'] = 'up'
        self.set_row(row_num, server_info)

    async def load_servers(self):
        server_file = self.start_folder / 'serverlist.toml'
        if not server_file.exists():
            return
        with open(server_file, 'rb') as f:
            data = tomllib.load(f)
        if 'known_servers' not in data:
            return
        async with asyncio.TaskGroup() as tg:
            for server in data['known_servers']:
                tg.create_task(self.test_server(server))

    def clear_table(self):
        self.table.clear()
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)

    def add_row(self, row: dict) -> int:
        row_count = self.table.rowCount()
        self.table.setRowCount(row_count + 1)
        for key, value in row.items():
            self.table.setItem(row_count, self.headers.index(key), QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        return row_count

    def set_row(self, row_num: int, row: dict):
        for key, value in row.items():
            self.table.setItem(row_num, self.headers.index(key), QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()


async def main(app):
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    widget = ServerWidget(find_start_folder())
    widget.show()
    QTimer.singleShot(0, lambda: widget.run_in_background(widget.load_servers()))
    await app_close_event.wait()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    asyncio.run(main(app), loop_factory=QEventLoop)
