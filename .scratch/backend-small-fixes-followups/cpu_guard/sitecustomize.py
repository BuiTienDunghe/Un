"""Test processes may reach only loopback services, never a live model endpoint."""
import ipaddress
import socket

_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex

def allowed(address):
    if not isinstance(address, tuple):
        return
    host, port = address[:2]
    if host == "localhost":
        local = True
    else:
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
    if not local or port in {11434, 11435}:
        raise OSError("CPU check blocked network outside disposable loopback services")

def connect(self, address):
    allowed(address)
    return _connect(self, address)

def connect_ex(self, address):
    allowed(address)
    return _connect_ex(self, address)

socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
