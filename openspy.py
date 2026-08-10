import asyncio
import secrets
import socket
import struct
import time

NONSTANDARD_PORT_FLAG = 0x10
PRIVATE_IP_FLAG = 0x02
NONSTANDARD_PRIVATE_PORT_FLAG = 0x20
ICMP_IP_FLAG = 0x08
HAS_KEYS_FLAG = 0x40
HAS_FULL_RULES_FLAG = 0x80

KEYTYPE_STRING = 0
KEYTYPE_BYTE = 1
KEYTYPE_SHORT = 2
KEYTYPE_INT = 3
SEND_FIELDS_FOR_ALL = 0x01

DEFAULT_FIELDS = (
    'hostname',
    'mapname',
    'numplayers',
    'maxplayers',
    # 'gametype',
    'gamemode',
    # 'gamever',
    # 'password',
    'hostport',
)


def _master_index(game_name: str) -> int:
    """Calculate the GameSpy master server index for a game."""
    h = 0
    for ch in game_name.lower().encode('ascii'):
        signed_h = h if h < 0x80000000 else h - 0x100000000
        h = (signed_h * -1664117991 + ch) & 0xFFFFFFFF
    return h % 20


def _make_challenge() -> bytes:
    """Generate an 8-byte GameSpy server-list challenge."""
    challenge = bytearray(8)
    challenge[0] = 33 + secrets.randbelow(93)
    oddmode = 0
    for i in range(1, 8):
        oddmode = ((challenge[i - 1] & 1) ^ (i & 1) ^ oddmode ^ (challenge[0] & 1) ^ (1 if challenge[0] < 79 else 0) ^ (
            1 if challenge[i - 1] < challenge[0] else 0))
        challenge[i] = 33 + secrets.randbelow(93)
        if (oddmode and not challenge[i] & 1) or (not oddmode and challenge[i] & 1):
            challenge[i] += 1
    return bytes(challenge)


class _GOACrypt:
    """GameSpy GOA/enctypeX stream cipher implementation."""

    def __init__(self, key: bytes):
        cards = list(range(256))
        rsum = 0
        keypos = 0
        for i in range(255, -1, -1):
            if i == 0:
                toswap = 0
            else:
                retry_limiter = 0
                mask = 1
                while mask < i:
                    mask = (mask << 1) + 1
                while True:
                    rsum = (cards[rsum] + key[keypos]) & 0xFF
                    keypos += 1
                    if keypos >= len(key):
                        keypos = 0
                        rsum = (rsum + len(key)) & 0xFF
                    toswap = mask & rsum
                    retry_limiter += 1
                    if retry_limiter > 11:
                        toswap %= i
                    if toswap <= i:
                        break
            cards[i], cards[toswap] = cards[toswap], cards[i]
        self.cards = cards
        self.rotor = cards[1]
        self.ratchet = cards[3]
        self.avalanche = cards[5]
        self.last_plain = cards[7]
        self.last_cipher = cards[rsum]

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt a chunk of enctypeX-encrypted data."""
        out = bytearray()
        cards = self.cards
        for value in data:
            old_rotor = self.rotor
            self.ratchet = (self.ratchet + cards[old_rotor]) & 0xFF
            self.rotor = (old_rotor + 1) & 0xFF
            swaptemp = cards[self.last_cipher]
            cards[self.last_cipher] = cards[self.ratchet]
            cards[self.ratchet] = cards[self.last_plain]
            cards[self.last_plain] = cards[self.rotor]
            cards[self.rotor] = swaptemp
            self.avalanche = (self.avalanche + cards[swaptemp]) & 0xFF
            self.last_plain = (value ^ cards[(cards[self.avalanche] + cards[self.rotor]) & 0xFF] ^ cards[
                cards[(cards[self.last_plain] + cards[self.last_cipher] + cards[self.ratchet]) & 0xFF]]) & 0xFF
            self.last_cipher = value
            out.append(self.last_plain)
        return bytes(out)


def _read_nts(data: bytes, pos: int):
    """Read a null-terminated GameSpy string and return its new position."""
    end = data.find(b'\0', pos)
    if end == -1:
        return None
    return data[pos:end], end + 1


def _decode_text(value: bytes) -> str:
    """Decode GameSpy text, falling back to Windows-1252 when needed."""
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('cp1252', errors='replace')


def _read_field_value(data: bytes, pos: int, field_type: int, popular_strings: list[str]):
    """Read a typed field value from a GameSpy server-list response."""
    if field_type == KEYTYPE_STRING:
        if len(data) <= pos:
            return None
        marker = data[pos]
        pos += 1
        if marker == 0xFF:
            result = _read_nts(data, pos)
            if result is None:
                return None
            raw, pos = result
            return _decode_text(raw), pos
        if marker < len(popular_strings):
            return popular_strings[marker], pos
        raise RuntimeError(f'Invalid popular string index: {marker}')
    if field_type == KEYTYPE_BYTE:
        return None if len(data) < pos + 1 else (data[pos], pos + 1)
    if field_type == KEYTYPE_SHORT:
        return None if len(data) < pos + 2 else (struct.unpack_from('>H', data, pos)[0], pos + 2)
    if field_type == KEYTYPE_INT:
        return None if len(data) < pos + 4 else (struct.unpack_from('>I', data, pos)[0], pos + 4)
    raise RuntimeError(f'Unsupported field type: {field_type}')


def _parse_server_list(data: bytes) -> list[dict] | None:
    """Parse a decrypted GameSpy server-list response."""
    if len(data) < 7:
        return None
    default_port = struct.unpack_from('>H', data, 4)[0]
    field_count = data[6]
    pos = 7
    field_defs = []
    for _ in range(field_count):
        if len(data) <= pos:
            return None
        field_type = data[pos]
        pos += 1
        result = _read_nts(data, pos)
        if result is None:
            return None
        raw_name, pos = result
        field_defs.append((_decode_text(raw_name), field_type))
    if len(data) <= pos:
        return None
    popular_count = data[pos]
    pos += 1
    popular_strings = []
    for _ in range(popular_count):
        result = _read_nts(data, pos)
        if result is None:
            return None
        raw, pos = result
        popular_strings.append(_decode_text(raw))
    servers = []
    while True:
        if len(data) < pos + 5:
            return None
        flags = data[pos]
        ip_raw = data[pos + 1:pos + 5]
        pos += 5
        if ip_raw == b'\xff\xff\xff\xff':
            return servers
        port = default_port
        if flags & NONSTANDARD_PORT_FLAG:
            if len(data) < pos + 2:
                return None
            port = struct.unpack_from('>H', data, pos)[0]
            pos += 2
        if flags & PRIVATE_IP_FLAG:
            if len(data) < pos + 4:
                return None
            pos += 4
        if flags & NONSTANDARD_PRIVATE_PORT_FLAG:
            if len(data) < pos + 2:
                return None
            pos += 2
        if flags & ICMP_IP_FLAG:
            if len(data) < pos + 4:
                return None
            pos += 4
        if flags & HAS_FULL_RULES_FLAG:
            raise RuntimeError('Unexpected OpenSpy full-rules response')
        fields = {}
        ip = socket.inet_ntoa(ip_raw)
        fields['ip'] = ip
        fields['port'] = port
        if flags & HAS_KEYS_FLAG:
            for field_name, field_type in field_defs:
                result = _read_field_value(data, pos, field_type, popular_strings)
                if result is None:
                    return None
                fields[field_name], pos = result
        servers.append(fields)


async def get_openspy_servers(
        game_name: str = 'coj2',
        secret_key: str = 'H0bx87',
        domain: str = 'openspy.net',
        master_host: str | None = None,
        master_port: int = 28910,
        timeout: float = 5.0,
        fields: tuple[str, ...] = DEFAULT_FIELDS
) -> list[dict]:
    if master_host is None:
        master_host = f'{game_name}.ms{_master_index(game_name)}.{domain}'
    challenge = _make_challenge()
    game = game_name.encode('ascii')
    requested_fields = ('\\' + '\\'.join(fields)).encode('ascii') if fields else b''
    options = SEND_FIELDS_FOR_ALL if fields else 0
    payload = (
            b'\x00'  # SERVER_LIST_REQUEST
            b'\x01'  # Protocol version
            b'\x03'  # Encoding version
            + struct.pack('<I', 0)  # Game version
            + game + b'\0'  # Query game
            + game + b'\0'  # Source game
            + challenge
            + b'\0'  # Filter
            + requested_fields + b'\0'  # Requested fields
            + struct.pack('>I', options)  # Request options
    )
    request = struct.pack('>H', len(payload) + 2) + payload
    reader, writer = await asyncio.wait_for(asyncio.open_connection(master_host, master_port), timeout=timeout)
    try:
        writer.write(request)
        await writer.drain()

        # Read and validate the encryption header.
        first = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
        crypt_len = first[0] ^ 0xEC
        if crypt_len != 10:
            rest = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            message = (first + rest).decode('utf-8', errors='replace')
            raise RuntimeError(f'OpenSpy rejected request: {message}')
        await asyncio.wait_for(reader.readexactly(crypt_len), timeout=timeout)

        # Read the server-side challenge used for key derivation.
        server_len_byte = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
        server_challenge_len = server_len_byte[0] ^ 0xEA
        server_challenge = await asyncio.wait_for(reader.readexactly(server_challenge_len), timeout=timeout)

        # Derive the enctypeX session key from both challenges and the game secret.
        key = bytearray(challenge)
        secret = secret_key.encode('ascii')
        for i, value in enumerate(server_challenge):
            index = (i * secret[i % len(secret)]) % 8
            key[index] ^= (key[i % 8] ^ value) & 0xFF

        # Decrypt incoming chunks until the complete server list can be parsed.
        crypt = _GOACrypt(bytes(key))
        plain = bytearray()
        while True:
            result = _parse_server_list(plain)
            if result is not None:
                return result
            chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if not chunk:
                raise RuntimeError('OpenSpy response ended unexpectedly')
            plain.extend(crypt.decrypt(chunk))
    finally:
        writer.close()
        await writer.wait_closed()


async def qr2_ping(host: str, port: int, timeout: float = 1.0) -> int | None:
    request_key = secrets.token_bytes(4)
    echo_data = secrets.token_bytes(4)
    request = b'\xfe\xfd\x02' + request_key + echo_data
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        start = time.perf_counter()
        await loop.sock_sendto(sock, request, (host, port))
        while True:
            data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 64), timeout=timeout)
            if addr[0] != host:
                continue
            if data != b'\x05' + request_key + echo_data:
                continue
            return round((time.perf_counter() - start) * 1000)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        sock.close()


async def main():
    servers = await get_openspy_servers()
    for server in servers:
        print(server)


if __name__ == '__main__':
    asyncio.run(main())
