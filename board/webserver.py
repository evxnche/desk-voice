# Tiny non-blocking HTTP server on the home Wi-Fi: the remote-control page (phone/Mac) and
# the Mac's agent hooks talk to the board directly, so nothing is polled from the cloud.
import socket

def _unquote(s):
    s = s.replace("+", " ")
    out, i = bytearray(), 0
    b = s.encode()
    while i < len(b):
        if b[i] == 37 and i + 2 < len(b):     # '%XX'
            try:
                out.append(int(b[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(b[i])
        i += 1
    return out.decode()

def _query(qs):
    q = {}
    for part in qs.split("&"):
        if part:
            k, _, v = part.partition("=")
            q[_unquote(k)] = _unquote(v)
    return q

class Server:
    def __init__(self, port=80):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(3)
        s.setblocking(False)
        self.sock = s

    def poll(self, handler):
        """Serve at most one waiting request. handler(method, path, query, body) -> (status, type, bytes)."""
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        try:
            conn.settimeout(2)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 8192:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
            head, _, body = data.partition(b"\r\n\r\n")
            lines = head.decode().split("\r\n")
            method, target = lines[0].split(" ")[:2]
            length = 0
            for line in lines[1:]:
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1])
            while len(body) < length:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                body += chunk
            path, _, qs = target.partition("?")
            status, ctype, payload = handler(method, path, _query(qs), body)
            if isinstance(payload, str):
                payload = payload.encode()
            conn.send(b"HTTP/1.1 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                      b"Cache-Control: no-store\r\nConnection: close\r\n\r\n" % (status, ctype.encode(), len(payload)))
            conn.sendall(payload)
        except Exception as e:
            print("web:", e)
        finally:
            conn.close()
