import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin

MAX_BYTES = 25 * 1024 * 1024

def public_target(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('图片地址必须是公网 HTTPS 地址')
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('禁止访问内网或保留地址')
    return p, addresses[0][4][0]

def download(url, target):
    # Pin the validated IP while retaining TLS hostname verification; no DNS rebind.
    for _ in range(4):
        p, ip = public_target(url)
        conn = http.client.HTTPSConnection(p.hostname, timeout=20)
        raw = socket.create_connection((ip, 443), timeout=20)
        conn.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=p.hostname)
        try:
            conn.request('GET', p.path + ('?' + p.query if p.query else ''), headers={'User-Agent': 'ImageCollector/0.1', 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status in (301,302,303,307,308):
                url = urljoin(url, response.getheader('Location', ''))
                continue
            if response.status != 200:
                raise ValueError('图片下载 HTTP ' + str(response.status))
            length = int(response.getheader('Content-Length', '0'))
            if length > MAX_BYTES:
                raise ValueError('图片超过 25 MiB 限制')
            total, start = 0, time.monotonic()
            with target.open('wb') as f:
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > MAX_BYTES or time.monotonic() - start > 90:
                        raise ValueError('图片超过下载大小或时间限制')
                    f.write(chunk)
            return
        finally:
            conn.close()
    raise ValueError('图片重定向次数过多')
