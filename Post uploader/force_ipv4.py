"""
force_ipv4.py — import karo SABSE PEHLE
Yeh Python ke socket.getaddrinfo ko patch karta hai taaki sirf
IPv4 addresses use ho. Instagram ka app session IPv6 pe www-backend
par route hota hai jo 403 deta hai.
"""
import socket

_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _ipv4_only
