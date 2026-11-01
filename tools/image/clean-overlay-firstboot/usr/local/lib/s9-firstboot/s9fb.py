"""Shared constants and checks of the first-boot account wizard (wizard, request helper, apply helper)."""
import os
import re

PLACEHOLDER = 's9user'
ROOT = os.environ.get('S9_FIRSTBOOT_ROOT', '/').rstrip('/') or '/'
STATE_DIR = 'var/lib/s9-ubports'
MARKER = STATE_DIR + '/firstboot.done'
REQUEST = STATE_DIR + '/firstboot.request'
ERROR_FILE = STATE_DIR + '/firstboot.error'
LOG = 'var/log/s9-firstboot.log'
MANIFEST = 'usr/local/share/s9-firstboot/rename.json'

USER_RE = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
HOST_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')
MIN_PASSWORD = 8
RESERVED = {
    'root', 'daemon', 'bin', 'sys', 'sync', 'games', 'man', 'lp', 'mail', 'news', 'uucp', 'proxy', 'www-data', 'backup',
    'list', 'irc', 'gnats', 'nobody', 'nogroup', 'sshd', 'messagebus', 'syslog', 'systemd-network', 'systemd-resolve',
    'systemd-timesync', 'systemd-coredump', 'polkitd', 'lightdm', 'colord', 'avahi', 'pulse', 'rtkit', 'ofono', 'radio',
    'system', 'shell', 'adm', 'sudo', 'audio', 'video', 'input', 'render', 'users', 'staff', 'admin', 'android', 'phablet',
}


def path(rel):
    """Absolute path of a file inside the (possibly relocated, for tests) root."""
    return os.path.join(ROOT, rel)


def _names(rel):
    out = set()
    try:
        with open(path(rel), errors='surrogateescape') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    out.add(line.split(':', 1)[0])
    except OSError:
        pass
    return out


def check_user(name):
    """Return an error text, or None when the user name is acceptable."""
    if not USER_RE.match(name or ''):
        return 'User name: lower-case letters, digits, "-" and "_"; it must start with a letter or "_" (32 characters at most).'
    if name != PLACEHOLDER and (name in RESERVED or name.startswith('systemd-')):
        return 'User name "%s" is reserved by the system. Choose another.' % name
    if name != PLACEHOLDER and (name in _names('etc/passwd') or name in _names('etc/group')):
        return 'User name "%s" already exists on this system. Choose another.' % name
    return None


def check_host(name):
    if not HOST_RE.match(name or ''):
        return 'Host name: lower-case letters, digits and "-" (not at the start or the end), 63 characters at most.'
    return None


def check_password(p1, p2=None):
    if p1 is None or len(p1) < MIN_PASSWORD:
        return 'Password: at least %d characters.' % MIN_PASSWORD
    if len(p1) > 128 or '\n' in p1 or '\0' in p1:
        return 'Password: up to 128 characters, on one line.'
    if p2 is not None and p1 != p2:
        return 'The two passwords are different.'
    return None
