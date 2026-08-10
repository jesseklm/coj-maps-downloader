import asyncio
import os
import socket
import time
from contextlib import closing

from singleshot_udp_client import SingleShotUDPClient


async def coj_bib_lan_query(host: str, port: int = 27632, timeout: float = 2.0) -> dict:
    ret_dict = {'host': host, 'port': port}
    token = os.urandom(11)
    req = b"\x05\x00\x00\x00\x00\x01\x00\x00\x00" + token + b"\x00\x17\x06"
    # print("token:", token)

    start_time: float = time.perf_counter()
    try:
        transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(SingleShotUDPClient,
                                                                                        remote_addr=(host, port))
    except socket.gaierror as e:
        ret_dict['error'] = f'{e=}'
        return ret_dict
    with closing(transport):
        transport.sendto(req)
        try:
            data = await asyncio.wait_for(protocol.future, timeout=timeout)
        except (asyncio.TimeoutError, ConnectionResetError, OSError) as e:
            ret_dict['error'] = f'{e=}'
            return ret_dict
    time_taken: float = (time.perf_counter() - start_time) * 1000.0

    if token != data[0x1:0xC]:
        print('token not matched!')

    # with open('datalog', 'wb') as fw:
    #     fw.write(data)

    server_name = data[0x51:0x91].decode('ascii', errors='ignore').replace('\x00', '')
    map_name = data[0x91:0xB1].decode('ascii', errors='ignore').replace('\x00', '')
    max_players = int(data[0xB1])
    current_players = int(data[0xB2])
    map_file = data[0xBF:0xDF].decode('ascii', errors='ignore').replace('\x00', '')
    map_file = map_file.removeprefix('&').removesuffix('&')
    ret_dict.update({
        'server_name': server_name,
        'map_name': map_name,
        'max_players': max_players,
        'current_players': current_players,
        'map_file': map_file,
        'ping': f'{time_taken:.1f}',
    })

    if data[0x4C:0x51] != b'\x00\x74\x27\x00\x00':
        print(server_name, host, port, '0x4C:0x51 differs:', ' '.join(f'{x:02x}' for x in data[0x4C:0x51]))

    # for i in range(0, 100):
    #     print(hex(crc16.modbus(data[i:0xDF])))
    # print(' '.join(f'{x:02x}' for x in data[0xDF:0xE1]))

    # print(' '.join(f'{x:02x}' for x in data[0x0C:0xDF]))
    # print(' '.join(f'{x:02x}' for x in data))
    return ret_dict


async def main():
    servers = [
        "127.0.0.1:27632",
    ]
    tasks = []
    async with asyncio.TaskGroup() as tg:
        for server in servers:
            host, port = server.rsplit(':', maxsplit=1)
            port = int(port)
            tasks.append(tg.create_task(coj_bib_lan_query(host, port)))
    for task in tasks:
        print(task.result())


if __name__ == "__main__":
    asyncio.run(main())
