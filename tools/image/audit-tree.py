#!/usr/bin/env python3
"""audit-tree.py - inventory, scrub and audit an extracted Galaxy S9 root tree before it
goes into an image that other people will receive.

    audit-tree.py inventory TREE                      read-only: what is in there (names and sizes only)
    audit-tree.py scrub     TREE --user NEW [...]     remove personal data, rename the account, install the
                                                      first-boot overlay (idempotent)
    audit-tree.py audit     TREE [--report FILE]      read-only gate: exit 1 if anything blocking is left

TREE is a directory holding the root file system (for example the result of untarring the
backup). Nothing here follows a symlink out of the tree and nothing is sent anywhere.
The password is read from the environment variable S9_PASSWORD_HASH (a crypt(3) hash), never
from the command line. The old user name is never printed: reports show <OLD>.
"""
import argparse, fnmatch, hashlib, os, re, shutil, stat, sys, time

SKIP_TOP = {'proc', 'sys', 'dev', 'run', 'mnt', 'media'}
MIB = 1 << 20

# ---- what the scrub removes ----------------------------------------------------------------
CLEAR_DIRS = [  # everything inside is removed (names can be identifiers, e.g. Bluetooth addresses)
    'tmp', 'var/tmp', 'var/crash', 'etc/NetworkManager/system-connections', 'var/lib/NetworkManager',
    'var/lib/bluetooth', 'var/lib/ofono', 'var/lib/dhcp', 'var/lib/upower', 'var/mail', 'var/spool/mail',
    'etc/apt/auth.conf.d', 'var/cache/man', 'var/cache/fontconfig', 'var/cache/cups', 'var/cache/lightdm',
    'var/cache/PackageKit', 'var/cache/apt/archives/partial',
    # the author's phone: call/SMS log, cast password/token, kernel logs, memory dumps, Android /data, caches
    'var/lib/android-data', 'var/lib/flatpak', 'var/lib/ubuntu-advantage', 'var/lib/s9-phone', 'var/lib/s9-cast',
    'var/lib/s9-lastkmsg', 'var/lib/s9-segv-cores', 'var/lib/dhcpcd', 'var/lib/udisks2', 'var/lib/blueman',
    'var/backups', 'var/lib/systemd/pstore', 'var/lib/s9-chrome-x11', 'var/lib/s9-docklike-fix', 'var/lib/s9-interna',
    'var/lib/colord',
]
CLEAR_FILES_ONLY = [  # files are removed, the directory skeleton stays
    'var/lib/AccountsService', 'var/lib/lightdm', 'var/lib/systemd/coredump', 'var/lib/systemd/linger',
    'var/lib/systemd/timers', 'var/lib/PackageKit', 'var/spool/cron/crontabs', 'var/lib/apt/periodic',
]
REMOVE_GLOBS = [
    'etc/ssh/ssh_host_*', 'etc/ssl/private/ssl-cert-snakeoil.key', 'etc/ssl/certs/ssl-cert-snakeoil.pem',
    'var/lib/systemd/random-seed', 'etc/passwd-', 'etc/shadow-', 'etc/group-', 'etc/gshadow-',
    'etc/subuid-', 'etc/subgid-', 'etc/.pwd.lock', 'etc/udev/rules.d/70-persistent-net.rules',
    'var/lib/logrotate/status', 'etc/wpa_supplicant/*.conf', 'etc/apt/auth.conf',
    'etc/netplan/90-NM-*.yaml', 'etc/security/opasswd', 'etc/apt/sources.list.d/claude-desktop.list',
    'usr/share/keyrings/claude-desktop-archive-keyring.asc', 'var/lib/s9-*.log', 'var/lib/s9-clock/events.log',
    'swapfile', 'var/cache/apt/archives/*.deb', 'var/cache/apt/*.bin', 'etc/cups/subscriptions.conf*', 'var/lib/dpkg/*-old', 'etc/NetworkManager/*.state',
]
NONFREE_PACKAGES = ['google-chrome-stable', 'google-chrome-beta', 'google-chrome-unstable',   # third-party packages:
                    'microsoft-edge-stable', 'claude-desktop',                                   # not part of the image
                    'hangover-wine', 'hangover-libarm64ecfex', 'hangover-libwow64fex', 'hangover-wowbox64']
DEFAULT_DROP = ['usr/local/bin/wine*', 'usr/local/bin/regedit', 'usr/bin/qemu-*-static', 'usr/local/sbin/*wine*',
                'etc/ssh/sshd_config.d/*debug-root*']
SECRET_FILES = ['etc/ppp/chap-secrets', 'etc/ppp/pap-secrets']       # keep only the comment lines
BACKUP_RE = re.compile(r'\.(before|pre|bak|backup|orig|old|rollback|disabled|superseded|save|dpkg-old|dpkg-new|'
                       r'dpkg-dist|dpkg-bak|ucf-old|ucf-new|ucf-dist)([-._~].*)?$|~$')
BACKUP_SCOPE = ('etc/', 'usr/local/', 'usr/bin/', 'usr/sbin/', 'usr/lib/', 'usr/libexec/', 'usr/share/pixmaps/', 'var/lib/')
SMALL_DIR_MAX = 1 * MIB
SMALL_DIR_BASES = ['.config', '.local/share']
SMALL_DIR_DENY = ['*keyring*', 'pulse', 'vlc', 'dconf', 'goa-*', 'gcr', 'seahorse', 'evolution', 'chromium*', 'google-chrome*',
                  'claude*', 'bravesoftware', 'mozilla', 'libreoffice', 'trash', 'gvfs*', '*metadata*', 'recently-used*',
                  'user-dirs.*', 'session*', '*cache*', 'ibus', 'fcitx*', 'nautilus', 'tracker*', 'xfce4-notifyd', 'wine*',
                  'box64', 'procps', 'pki', 'remmina*', 'debauchee', 'barrier*', 'flatpak', 's9-telefone', 'cpak', 'kio', 'kservices5', 'enchant', 'sni-qt', 'xdg-desktop-portal', 'Code', 'code*', 'pip', 'yarn', 'npm*', 'ssh', 'gnupg*']
OPT_KEEP = ('s9-', 'mesa-turnip-kgsl', 'mesa-kgsl-peekaboo', 'halium-overlay')
KEEP_HOME = ['.config/xfce4', '.config/menus', '.config/autostart', '.config/Thunar', '.config/gtk-3.0', '.config/gtk-2.0',
             '.config/mimeapps.list', '.config/fontconfig', '.config/systemd/user', '.local/share/applications',
             'Desktop', '.xprofile', '.profile', '.bashrc', '.bash_logout', '.Xresources', '.gtkrc-2.0']
DENY_IN_KEPT = ['*recent*', '*history*', '*.log', '*.sqlite*', '*cookie*', '*bookmark*', '*token*', '*secret*',
                '*password*', '*.key', '*.pem', '*.xbel', '*.lock', '*.core', 'sessions', 'xfce4-session-*']
LAUNCHER_DENY = re.compile(r'wine|office|soda|\.exe|bottles', re.I)   # launchers of removed apps
MAX_KEPT_FILE = 5 * MIB

# ---- what the audit accepts --------------------------------------------------------------------
ALLOW_UNOWNED = ('usr/local/', 'usr/bin/miral-', 'usr/bin/Xwayland', 'usr/lib/aarch64-linux-gnu/mir1/', 'var/lib/s9-',
                 'var/lib/lxc-android-config/', 'var/lib/colord/', 'opt/s9-', 'opt/mesa-turnip-kgsl', 'opt/mesa-kgsl-peekaboo', 'opt/halium-overlay',
                 'var/lib/lxc/android/', 'usr/lib/modules/', 'var/lib/dpkg/', 'var/lib/apt/', 'var/cache/',
                 'var/log/', 'var/lib/systemd/', 'var/lib/dbus/', 'var/lib/ucf/', 'var/lib/polkit-1/',
                 'var/lib/AccountsService/', 'var/lib/logrotate/', 'var/lib/pam/', 'var/lib/misc/',
                 'var/lib/command-not-found/', 'var/lib/python/', 'var/lib/snapd/', 'var/lib/fwupd/')
GENERATED = [re.compile(p) for p in (
    r'__pycache__/', r'\.py[co]$', r'^usr/lib/locale/locale-archive', r'icon-theme\.cache$', r'^usr/share/mime/',
    r'mimeinfo\.cache$', r'gschemas\.compiled$', r'giomodule\.cache$', r'loaders\.cache$', r'immodules\.cache$',
    r'/fonts\.(dir|scale|cache-\d)$', r'/hwdb\.bin$', r'/plugins\.dat$', r'^usr/share/info/dir', r'^usr/lib/modules/.*/modules\.', r'^usr/share/glib-2\.0/',
    r'^usr/lib/python3/dist-packages/.*\.egg-info', r'^usr/share/applications/.*\.desktop$', r'^usr/share/icons/.*/\.icon-theme\.cache')]
BLOB_EXT = ('.so', '.ko', '.bin', '.img', '.mbn', '.elf', '.apk', '.jar', '.exe', '.dll', '.msi', '.deb', '.fw', '.mdt')
FORBIDDEN_PATHS = ['opt/google', 'opt/wine*', 'opt/llvm-mingw*', 'root/.ssh', 'etc/ssh/ssh_host_*', 'swapfile']
SECRET_BLOCK = {
    'private key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'password hash': re.compile(r'\$(?:5|6|y|2[aby])\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{20,}'),
}
SECRET_REVIEW = {
    'password-like assignment': re.compile(r'(?i)\b(?:psk|password|passwd|passphrase|apikey|api_key|token)\b\s*[=:]\s*["\']?[A-Za-z0-9/+_.\-]{6,}'),
    'e-mail address': re.compile(r'\b[A-Za-z0-9._%+-]+@(?!example\.|localhost|users\.noreply|\d+\.service)[A-Za-z0-9-]+\.[A-Za-z]{2,}\b'),
    'MAC address': re.compile(r'\b(?!00:00:00:00:00:00|ff:ff:ff:ff:ff:ff)(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b'),
    '15-digit number (IMEI?)': re.compile(r'(?<![0-9.])\d{15}(?![0-9.])'),
}
BENIGN_MAIL = re.compile(r'@(?:ubuntu|canonical|debian|gnu|kernel|lists\.|freedesktop|gnome|xfce|mozilla|google|github|gitlab|redhat|suse|qualcomm|linaro|ubports|gmx|apache|python|x\.org|nvidia|intel|amd)', re.I)


# ---- helpers --------------------------------------------------------------------------------
def human(n):
    for u in ('B', 'KiB', 'MiB', 'GiB'):
        if n < 1024 or u == 'GiB':
            return '%d %s' % (n, u) if u == 'B' else '%.1f %s' % (n, u)
        n /= 1024.0


def host(tree, rel):
    """Host path of TREE/rel, resolving symlinks as a chroot would; the last component is not followed."""
    pending = [p for p in rel.split('/') if p and p != '.']
    cur, hops = [], 0
    while pending:
        p = pending.pop(0)
        if p == '..':
            cur = cur[:-1]
            continue
        path = os.path.join(tree, *cur, p)
        if pending and os.path.islink(path):
            hops += 1
            if hops > 40:
                raise OSError('too many symlinks: ' + rel)
            t = os.readlink(path)
            if t.startswith('/'):
                cur = []
            pending = [x for x in t.split('/') if x] + pending
        else:
            cur.append(p)
    return os.path.join(tree, *cur) if cur else tree


def remove_tree(path):
    """Delete without ever following a symlink."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        os.unlink(path)
        return 1
    n = 0
    for e in os.listdir(path):
        n += remove_tree(os.path.join(path, e))
    os.rmdir(path)
    return n + 1


def clear_dir(path):
    n = 0
    if os.path.isdir(path) and not os.path.islink(path):
        for e in os.listdir(path):
            n += remove_tree(os.path.join(path, e))
    return n


def norm(p):  # usr-merge: /bin/x == /usr/bin/x
    for a in ('bin', 'sbin', 'lib', 'lib64', 'lib32', 'libx32'):
        if p == a or p.startswith(a + '/'):
            return 'usr/' + p
    return p


def walk(tree, rel='', skip_top=SKIP_TOP):
    base = os.path.join(tree, rel) if rel else tree
    try:
        entries = list(os.scandir(base))
    except OSError:
        return
    for e in entries:
        r = rel + '/' + e.name if rel else e.name
        if not rel and e.name in skip_top:
            continue
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            yield from walk(tree, r, skip_top)
        else:
            yield r, st


def read_text_file(path, limit=4 * MIB):
    """Return decoded text or None (binary, ELF, too big, unreadable)."""
    try:
        with open(path, 'rb') as f:
            head = f.read(8192)
            if b'\0' in head or head[:4] == b'\x7fELF':
                return None
            rest = f.read(limit + 1 - len(head))
    except OSError:
        return None
    data = head + rest
    if len(data) > limit:
        return None
    return data.decode('utf-8', 'surrogateescape')


def is_elf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except OSError:
        return False


class Tree:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        for must in ('etc/passwd', 'var/lib/dpkg/status'):
            if not os.path.exists(host(self.root, must)):
                sys.exit('ERROR: %s does not look like a root tree (%s missing)' % (root, must))
        self._owned = None
        self._modconf = None

    def h(self, rel):
        return host(self.root, rel)

    @property
    def owned(self):
        if self._owned is None:
            s = set()
            info = self.h('var/lib/dpkg/info')
            for fn in os.listdir(info):
                if fn.endswith('.list'):
                    with open(os.path.join(info, fn), 'r', errors='surrogateescape') as f:
                        for line in f:
                            line = line.rstrip('\n')
                            if line.startswith('/') and len(line) > 1:
                                s.add(norm(line[1:]))
            self._owned = s
        return self._owned

    @property
    def modified_conffiles(self):
        if self._modconf is None:
            mod, cur = set(), False
            with open(self.h('var/lib/dpkg/status'), 'r', errors='surrogateescape') as f:
                for line in f:
                    if line.startswith('Conffiles:'):
                        cur = True
                        continue
                    if cur and line.startswith(' '):
                        parts = line.split()
                        if len(parts) >= 2 and parts[0].startswith('/'):
                            p = self.h(parts[0][1:])
                            try:
                                with open(p, 'rb') as g:
                                    if hashlib.md5(g.read()).hexdigest() != parts[1]:
                                        mod.add(norm(parts[0][1:]))
                            except OSError:
                                pass
                    else:
                        cur = False
            self._modconf = mod
        return self._modconf

    def interesting(self, rel):
        """Files whose content is the author's work or was changed by the author (not pristine packages)."""
        if rel.startswith(('usr/local/', 'opt/', 'home/', 'root/')):
            return True
        if rel.startswith(('var/lib/dpkg', 'var/lib/apt', 'var/cache', 'var/log', 'usr/share/doc', 'usr/share/man',
                           'usr/share/locale', 'usr/lib/python3', 'usr/share/zoneinfo', 'etc/alternatives/', 'etc/ssl/certs/',
                           'etc/rc0.d/', 'etc/rc1.d/', 'etc/rc2.d/', 'etc/rc3.d/', 'etc/rc4.d/', 'etc/rc5.d/', 'etc/rc6.d/',
                           'etc/rcS.d/')) or rel == 'etc/ld.so.cache':
            return False
        n = norm(rel)
        return n not in self.owned or n in self.modified_conffiles

    def accounts(self):
        out = []
        with open(self.h('etc/passwd'), 'r', errors='surrogateescape') as f:
            for line in f:
                p = line.rstrip('\n').split(':')
                if len(p) >= 7:
                    out.append(p)
        return out

    def old_user(self, forced=None):
        if forced:
            return forced
        cands = [p[0] for p in self.accounts() if p[2] == '1000']
        if len(cands) != 1:
            sys.exit('ERROR: cannot tell which account is the desktop user (uid 1000 entries: %d). Use --old-user.' % len(cands))
        return cands[0]


def user_regex(old):
    risky = len(old) < 4 or old in {'user', 'ubuntu', 'admin', 'phablet', 'root', 'test', 'pi', 'android', 'default'}
    if risky:
        pats = [r'(?<=/home/)%s(?![A-Za-z0-9_.-])' % re.escape(old),
                r'(?<=User=)%s(?![A-Za-z0-9_.-])' % re.escape(old),
                r'(?<=Group=)%s(?![A-Za-z0-9_.-])' % re.escape(old),
                r'(?<=autologin-user=)%s(?![A-Za-z0-9_.-])' % re.escape(old),
                r'(?<=S9_USER=)%s(?![A-Za-z0-9_.-])' % re.escape(old),
                r'(?m)^%s(?=[ \t]+ALL)' % re.escape(old),
                r'(?<=~)%s(?![A-Za-z0-9_.-])' % re.escape(old)]
        return re.compile('|'.join(pats)), True
    return re.compile(r'(?<![A-Za-z0-9])%s(?![A-Za-z0-9])' % re.escape(old)), False


def du(path):
    total = 0
    for _, st in walk(path, '', set()):
        total += st.st_size
    return total


def opt_references(t):
    """{/opt/<name>: number of files that mention it}. Roots outside /opt, then transitively inside the
    referenced /opt directories. A directory with 0 is not used by anything that is kept."""
    ob = t.h('opt')
    names = sorted(os.listdir(ob)) if os.path.isdir(ob) else []
    pat = re.compile(r'/opt/([A-Za-z0-9._+-]+)')
    counts = {n: 0 for n in names}

    def scan(rel):
        txt = read_text_file(t.h(rel), 2 * MIB)
        if not txt:
            return set()
        hit = set()
        for m in pat.finditer(txt):
            tok = m.group(1)
            if tok in counts:
                hit.add(tok)
            elif len(tok) >= 6:  # a name built at run time, e.g. /opt/s9-mir-lib-v${N}: every directory with that prefix
                hit.update(n for n in names if n.startswith(tok))
        return hit
    for top in ('etc', 'usr/local', 'usr/lib/systemd', 'usr/libexec', 'usr/share/applications', 'usr/share/dbus-1', 'home', 'var/lib'):
        if not os.path.isdir(t.h(top)):
            continue
        for rel, st in walk(t.root, top):
            if rel.startswith(('var/lib/dpkg', 'var/lib/apt', 'var/lib/android-data', 'var/lib/lxc')) or not stat.S_ISREG(st.st_mode):
                continue
            if st.st_size > 2 * MIB:
                continue
            for n in scan(rel):
                counts[n] += 1
    todo = [n for n in names if counts[n]]
    seen = set(todo)
    while todo:
        n = todo.pop()
        for rel, st in walk(t.root, 'opt/' + n):
            if stat.S_ISREG(st.st_mode) and st.st_size <= 2 * MIB:
                for m in scan(rel):
                    if m != n:
                        counts[m] += 1
                        if m not in seen:
                            seen.add(m)
                            todo.append(m)
    return counts


# ---- inventory -------------------------------------------------------------------------------
def cmd_inventory(a):
    t = Tree(a.tree)
    old = t.old_user(a.old_user)
    mask = lambda s: re.sub(r'(?<![A-Za-z0-9])%s(?![A-Za-z0-9])' % re.escape(old), '<OLD>', s)
    print('== accounts')
    for p in t.accounts():
        if p[0] == old or (p[2].isdigit() and int(p[2]) >= 1000 and p[0] != 'nobody'):
            print('   %s uid=%s gid=%s shell=%s home=%s' % (mask(p[0]), p[2], p[3], p[6], mask(p[5])))
    groups = []
    with open(t.h('etc/group'), errors='surrogateescape') as f:
        for line in f:
            g = line.rstrip('\n').split(':')
            if len(g) >= 4 and old in g[3].split(','):
                groups.append(g[0])
    print('   <OLD> is a member of: ' + ', '.join(groups))
    print('== /home (depth 2, size)')
    hb = t.h('home')
    for d in sorted(os.listdir(hb)) if os.path.isdir(hb) else []:
        p = os.path.join(hb, d)
        print('   %-40s %10s' % (mask('home/' + d), human(du(p))))
        if os.path.isdir(p):
            rows = []
            for e in os.listdir(p):
                q = os.path.join(p, e)
                sz = du(q) if os.path.isdir(q) and not os.path.islink(q) else os.lstat(q).st_size
                rows.append((sz, e))
                if os.path.isdir(q) and not os.path.islink(q) and e in ('.config', '.local', '.local/share'):
                    for e2 in os.listdir(q):
                        q2 = os.path.join(q, e2)
                        s2 = du(q2) if os.path.isdir(q2) and not os.path.islink(q2) else os.lstat(q2).st_size
                        rows.append((s2, e + '/' + e2))
                        if e == '.local' and e2 == 'share' and os.path.isdir(q2) and not os.path.islink(q2):
                            for e3 in os.listdir(q2):
                                q3 = os.path.join(q2, e3)
                                s3 = du(q3) if os.path.isdir(q3) and not os.path.islink(q3) else os.lstat(q3).st_size
                                rows.append((s3, '.local/share/' + e3))
            for sz, e in sorted(rows, reverse=True)[:260]:
                print('      %10s  %s' % (human(sz), mask(e)))
    print('== /root')
    rb = t.h('root')
    for e in sorted(os.listdir(rb)) if os.path.isdir(rb) else []:
        print('   ', e)
    print('== /opt (size; "owned" = at least one file belongs to a package)')
    ob = t.h('opt')
    for e in sorted(os.listdir(ob)) if os.path.isdir(ob) else []:
        owned = any(n == 'opt/' + e or n.startswith('opt/' + e + '/') for n in t.owned)
        print('   %-40s %10s  %s' % (e, human(du(os.path.join(ob, e))), 'owned' if owned else 'not from a package'))
    print('== /usr/local (files)')
    cnt = 0
    for rel, st in sorted(walk(t.root, 'usr/local')):
        cnt += 1
        if cnt <= 150:
            print('   %9s  %s' % (human(st.st_size), mask(rel)))
    print('   total: %d files%s' % (cnt, '' if cnt <= 150 else ' (first 150 shown)'))
    print('== /etc files that are not from a package or differ from it (names only)')
    n = 0
    for rel, st in sorted(walk(t.root, 'etc')):
        if t.interesting(rel) and not stat.S_ISLNK(st.st_mode):
            n += 1
            if n <= 400:
                print('   ', mask(rel))
    print('   total: %d%s' % (n, '' if n <= 400 else ' (first 400 shown)'))
    print('== /opt directories not referenced by anything outside themselves (0 = unused)')
    for nme, c in sorted(opt_references(t).items()):
        if c == 0:
            print('    %s' % nme)
    print('== non-free packages registered in dpkg')
    st = open(t.h('var/lib/dpkg/status'), errors='surrogateescape').read()
    for pkg in NONFREE_PACKAGES:
        if re.search(r'(?m)^Package: %s$' % re.escape(pkg), st):
            print('   ', pkg)
    print('== biggest directories (depth 3)')
    sizes = {}
    for rel, s in walk(t.root):
        parts = rel.split('/')[:3]
        key = '/'.join(parts[:-1]) if len(parts) > 1 else '(root files)'
        for i in range(1, min(len(parts), 3)):
            k = '/'.join(parts[:i])
            sizes[k] = sizes.get(k, 0) + s.st_size
    for k, v in sorted(sizes.items(), key=lambda kv: -kv[1])[:30]:
        print('   %10s  %s' % (human(v), mask(k)))


# ---- scrub -------------------------------------------------------------------------------------
def log(msg):
    print('   ' + msg)


def copy_filtered(src, dst, relname, stats):
    """Copy src (file/symlink/dir) to dst honouring DENY_IN_KEPT; returns True if something was copied."""
    base = os.path.basename(src)
    if any(fnmatch.fnmatch(base.lower(), pat) for pat in DENY_IN_KEPT):
        stats['denied'] += 1
        return False
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(src), dst)
        return True
    if stat.S_ISDIR(st.st_mode):
        os.makedirs(dst, exist_ok=True)
        shutil.copystat(src, dst)
        for e in sorted(os.listdir(src)):
            copy_filtered(os.path.join(src, e), os.path.join(dst, e), relname + '/' + e, stats)
        return True
    if not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size > MAX_KEPT_FILE:
        stats['big'].append(relname)
        return False
    if (relname.startswith('Desktop/') or relname.startswith('.local/share/applications/')) and relname.endswith('.desktop'):
        txt = read_text_file(src) or ''
        if LAUNCHER_DENY.search(txt):
            stats['launchers'].append(relname)
            return False
    shutil.copy2(src, dst)
    return True


def cmd_scrub(a):
    t = Tree(a.tree)
    old = t.old_user(a.old_user)
    new = a.user
    if not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', new) or new == 'root':
        sys.exit('ERROR: --user must be a lower-case account name other than root')
    pwhash = os.environ.get('S9_PASSWORD_HASH', '')
    if not re.match(r'^\$(?:5|6|y)\$', pwhash):
        sys.exit('ERROR: set S9_PASSWORD_HASH to a crypt(3) hash ($6$..., $y$... or $5$...)')
    hostname = a.hostname
    today = int(time.time() // 86400)
    ids = [p for p in t.accounts() if p[0] == old][0]
    uid, gid = int(ids[2]), int(ids[3])
    t.owned  # load before files disappear
    t.modified_conffiles

    print('== scrub: remove runtime state, logs and caches')
    n = 0
    for d in CLEAR_DIRS:
        n += clear_dir(t.h(d))
    for d in CLEAR_FILES_ONLY:
        base = t.h(d)
        if os.path.isdir(base) and not os.path.islink(base):
            for dp, dn, fn in os.walk(base):
                for f in fn:
                    os.unlink(os.path.join(dp, f))
                    n += 1
    for pat in REMOVE_GLOBS:
        dirpart, base = os.path.split(pat)
        d = t.h(dirpart) if dirpart else t.root
        if os.path.isdir(d):
            for e in os.listdir(d):
                if fnmatch.fnmatch(e, base):
                    n += remove_tree(os.path.join(d, e))
    for rel, st in list(walk(t.root, 'var/log')):
        p = t.h(rel)
        if rel.endswith(('.gz', '.xz', '.1', '.old', '.journal', '.journal~')) or '/journal/' in rel:
            os.unlink(p)
        elif stat.S_ISREG(st.st_mode):
            open(p, 'wb').close()
        n += 1
    jd = t.h('var/log/journal')
    if os.path.isdir(jd):
        clear_dir(jd)
    log('removed/emptied %d entries' % n)

    mid = t.h('etc/machine-id')
    open(mid, 'wb').close()
    os.chmod(mid, 0o644)
    dm = t.h('var/lib/dbus/machine-id')
    if os.path.lexists(dm):
        os.unlink(dm)
        os.symlink('/etc/machine-id', dm)
    log('machine-id emptied (systemd makes a new one at the first boot); ssh host keys removed')

    print('== scrub: /root and /home')
    rb = t.h('root')
    if os.path.isdir(rb):
        for e in os.listdir(rb):
            if e not in ('.bashrc', '.profile'):
                remove_tree(os.path.join(rb, e))
    hb = t.h('home')
    os.makedirs(hb, exist_ok=True)
    stats = {'denied': 0, 'big': [], 'launchers': []}
    oldhome = os.path.join(hb, old)
    newtmp = os.path.join(hb, '.s9-new-home')
    remove_tree(newtmp)
    os.makedirs(newtmp, mode=0o755)
    if os.path.isdir(oldhome):
        for item in KEEP_HOME + (a.keep_home or []):
            src = os.path.join(oldhome, item)
            if os.path.lexists(src):
                dst = os.path.join(newtmp, item)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                copy_filtered(src, dst, item, stats)
        kept_small, dropped_small = [], []
        for base in SMALL_DIR_BASES:
            bdir = os.path.join(oldhome, base)
            if not os.path.isdir(bdir) or os.path.islink(bdir):
                continue
            for e in sorted(os.listdir(bdir)):
                q = os.path.join(bdir, e)
                rel = base + '/' + e
                if any(rel == k or rel.startswith(k + '/') for k in KEEP_HOME):
                    continue
                if any(fnmatch.fnmatch(e.lower(), pat.lower()) for pat in SMALL_DIR_DENY):
                    dropped_small.append(rel)
                    continue
                sz = du(q) if os.path.isdir(q) and not os.path.islink(q) else os.lstat(q).st_size
                if sz > SMALL_DIR_MAX:
                    dropped_small.append('%s (%s)' % (rel, human(sz)))
                    continue
                dst = os.path.join(newtmp, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if copy_filtered(q, dst, rel, stats):
                    kept_small.append(rel)
        log('small config/data entries kept: ' + (', '.join(kept_small) or '(none)'))
        log('entries not kept (denied by name or > 1 MiB): %d' % len(dropped_small))
        for r in dropped_small:
            log('   not kept: ' + r)
    for e in os.listdir(hb):
        if e != '.s9-new-home':
            remove_tree(os.path.join(hb, e))
    newhome = os.path.join(hb, new)
    os.rename(newtmp, newhome)
    os.chmod(newhome, 0o750)
    skel = t.h('etc/skel')
    if os.path.isdir(skel):
        for e in os.listdir(skel):
            dst = os.path.join(newhome, e)
            if not os.path.lexists(dst) and os.path.isfile(os.path.join(skel, e)):
                shutil.copy2(os.path.join(skel, e), dst)
    log('home rebuilt from the keep-list (%d files dropped by name filters, %d too big, %d launchers of removed apps)'
        % (stats['denied'], len(stats['big']), len(stats['launchers'])))
    for r in stats['launchers']:
        log('  dropped launcher: ' + r)
    for r in stats['big']:
        log('  dropped (>5 MiB): ' + r)

    print('== scrub: backups/rollbacks of the author, default drops, secret files')
    nb = 0
    for top in ('etc', 'usr', 'var/lib'):
        for rel, st in list(walk(t.root, top)):
            if not rel.startswith(BACKUP_SCOPE) or rel.startswith(('etc/alternatives/', 'var/lib/dpkg', 'var/lib/apt', 'usr/lib/python3')):
                continue
            if BACKUP_RE.search(rel.rsplit('/', 1)[-1]) and norm(rel) not in t.owned:
                os.unlink(t.h(rel))
                nb += 1
    log('%d unowned backup/rollback/disabled files removed' % nb)
    for g in DEFAULT_DROP:
        for rel, st in list(walk(t.root)):
            if fnmatch.fnmatch(rel, g) and norm(rel) not in t.owned:
                os.unlink(t.h(rel))
                log('dropped: ' + rel)
    for rel in SECRET_FILES:
        p = t.h(rel)
        if os.path.isfile(p):
            lines = open(p, errors='surrogateescape').read().split('\n')
            keep = [l for l in lines if l.startswith('#') or not l.strip()]
            if len(keep) != len(lines):
                open(p, 'w', errors='surrogateescape').write('\n'.join(keep).rstrip('\n') + '\n')
                log('secrets removed from ' + rel)

    print('== scrub: non-free packages and /opt')
    status_path = t.h('var/lib/dpkg/status')
    text = open(status_path, 'r', errors='surrogateescape').read()
    stanzas = text.split('\n\n')
    kept, gone = [], []
    for s in stanzas:
        m = re.match(r'Package: (\S+)', s.lstrip('\n'))
        if m and m.group(1) in NONFREE_PACKAGES:
            gone.append(m.group(1))
        else:
            kept.append(s)
    for pkg in gone:
        lst = t.h('var/lib/dpkg/info/%s.list' % pkg)
        files = []
        if os.path.exists(lst):
            files = [l.rstrip('\n') for l in open(lst, errors='surrogateescape') if l.startswith('/')]
        for f in sorted(files, key=len, reverse=True):
            p = t.h(f[1:])
            if os.path.islink(p) or os.path.isfile(p):
                os.unlink(p)
        for fn in os.listdir(t.h('var/lib/dpkg/info')):
            if fn.startswith(pkg + '.') or fn.startswith(pkg + ':'):
                os.unlink(os.path.join(t.h('var/lib/dpkg/info'), fn))
        for f in sorted(files, key=len, reverse=True):
            p = t.h(f[1:])
            if os.path.isdir(p) and not os.path.islink(p) and not os.listdir(p):
                os.rmdir(p)
        log('package %s unregistered and its files removed' % pkg)
    if gone:
        open(status_path, 'w', errors='surrogateescape').write('\n\n'.join(kept))
    t._owned = None
    ob = t.h('opt')
    if os.path.isdir(ob):
        for e in sorted(os.listdir(ob)):
            if e.startswith(OPT_KEEP) or e in OPT_KEEP:
                continue
            if any(n == 'opt/' + e or n.startswith('opt/' + e + '/') for n in t.owned):
                log('/opt/%s belongs to a package: kept' % e)
                continue
            sz = du(os.path.join(ob, e))
            remove_tree(os.path.join(ob, e))
            log('/opt/%s removed (%s)' % (e, human(sz)))
    if a.prune_opt_unreferenced:
        for nme, c in sorted(opt_references(t).items()):
            if c == 0 and nme.startswith('s9-') and os.path.isdir(t.h('opt/' + nme)):
                sz = du(t.h('opt/' + nme))
                remove_tree(t.h('opt/' + nme))
                log('/opt/%s removed: nothing references it (%s)' % (nme, human(sz)))
    for g in a.drop or []:
        for rel, st in list(walk(t.root)):
            if fnmatch.fnmatch(rel, g.lstrip('/')):
                os.unlink(t.h(rel))
                log('dropped by --drop: ' + rel)

    print('== scrub: account <OLD> -> %s' % new)

    def rewrite(rel, fn):
        p = t.h(rel)
        if not os.path.exists(p):
            return
        with open(p, 'r', errors='surrogateescape') as f:
            lines = f.read().split('\n')
        trailing = lines and lines[-1] == ''
        out = []
        for l in lines:
            if l == '':
                continue
            r = fn(l.split(':'))
            if r is not None:
                out.append(':'.join(r))
        with open(p, 'w', errors='surrogateescape') as f:
            f.write('\n'.join(out) + ('\n' if trailing or out else ''))

    dropped_users = set()

    def fix_passwd(f):
        if f[0] == old:
            f[0], f[4] = new, new
            f[5] = '/home/' + new
        elif f[2].isdigit() and int(f[2]) >= 1000 and f[0] != 'nobody':
            dropped_users.add(f[0])
            return None
        return f
    rewrite('etc/passwd', fix_passwd)
    dropped_groups = set()

    def fix_group(f):
        if f[0] == old:
            f[0] = new
        elif f[2].isdigit() and int(f[2]) >= 1000 and f[0] not in ('nogroup', new):
            dropped_groups.add(f[0])
            return None
        if len(f) >= 4:
            f[3] = ','.join(new if m == old else m for m in f[3].split(',') if m and m not in dropped_users)
        return f
    rewrite('etc/group', fix_group)

    def fix_shadow(f):
        if f[0] == old:
            f[0], f[1], f[2] = new, pwhash, str(today)
        elif f[0] in dropped_users:
            return None
        elif f[0] == 'root':
            f[1] = '!'
        elif f[1] not in ('*', '!', '!!', ''):
            f[1] = '!'
        return f
    rewrite('etc/shadow', fix_shadow)

    def fix_gshadow(f):
        if f[0] == old:
            f[0] = new
        elif f[0] in dropped_groups:
            return None
        if len(f) >= 4:
            f[2] = ','.join(new if m == old else m for m in f[2].split(',') if m)
            f[3] = ','.join(new if m == old else m for m in f[3].split(',') if m and m not in dropped_users)
        return f
    rewrite('etc/gshadow', fix_gshadow)
    for rel in ('etc/subuid', 'etc/subgid'):
        rewrite(rel, lambda f: ([new] + f[1:]) if f[0] == old else (None if f[0] in dropped_users else f))
    # home ownership
    for dirpath, dirs, files in os.walk(newhome):
        os.lchown(dirpath, uid, gid)
        for fn in files:
            os.lchown(os.path.join(dirpath, fn), uid, gid)
    log('passwd/shadow/group/gshadow rewritten; root locked; %d other human account(s) dropped' % len(dropped_users))

    rx, risky = user_regex(old)
    if risky:
        log('the old user name is short or common: only contextual replacements (/home/<OLD>, User=, sudoers lines)')
    skip_files = {'etc/passwd', 'etc/shadow', 'etc/group', 'etc/gshadow', 'etc/subuid', 'etc/subgid'}
    changed = 0
    renamed = 0
    links = 0
    for top in ('etc', 'usr', 'opt', 'var', 'home', 'root', 'srv'):
        if not os.path.isdir(t.h(top)):
            continue
        for rel, st in list(walk(t.root, top)):
            if rel in skip_files or rel.startswith(('var/lib/dpkg', 'var/lib/apt', 'var/cache', 'var/log')):
                continue
            p = t.h(rel)
            if stat.S_ISLNK(st.st_mode):
                tg = os.readlink(p)
                nt = rx.sub(new, tg)
                if nt != tg and t.interesting(rel):
                    os.unlink(p)
                    os.symlink(nt, p)
                    links += 1
                continue
            if not stat.S_ISREG(st.st_mode) or not t.interesting(rel):
                continue
            txt = read_text_file(p)
            if txt is None:
                continue
            nt = rx.sub(new, txt)
            if nt != txt:
                with open(p, 'w', errors='surrogateescape') as f:
                    f.write(nt)
                changed += 1
    for top in ('etc', 'usr/local', 'opt', 'var/lib', 'home'):
        base = t.h(top)
        for dirpath, dirs, files in os.walk(base, topdown=False):
            for nme in files + dirs:
                if nme != old and (risky or not rx.search(nme)):
                    continue
                src = os.path.join(dirpath, nme)
                dst = os.path.join(dirpath, new if nme == old else rx.sub(new, nme))
                if src != dst and not os.path.lexists(dst):
                    os.rename(src, dst)
                    renamed += 1
    log('text files rewritten: %d, symlinks retargeted: %d, paths renamed: %d' % (changed, links, renamed))

    print('== scrub: host name and first-boot overlay')
    open(t.h('etc/hostname'), 'w').write(hostname + '\n')
    open(t.h('etc/hosts'), 'w').write('127.0.0.1 localhost\n127.0.1.1 %s\n\n::1 ip6-localhost ip6-loopback\n'
                                      'fe00::0 ip6-localnet\nff00::0 ip6-mcastprefix\nff02::1 ip6-allnodes\n'
                                      'ff02::2 ip6-allrouters\n' % hostname)
    log('host name: ' + hostname)
    if a.overlay:
        wants = t.h('etc/systemd/system/multi-user.target.wants')
        os.makedirs(wants, exist_ok=True)
        for dirpath, dirs, files in os.walk(a.overlay):
            for fn in files:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, a.overlay)
                dst = t.h(rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.lexists(dst):
                    os.unlink(dst)
                shutil.copy2(src, dst)
                os.chown(dst, 0, 0)
                if rel.startswith('etc/systemd/system/') and rel.endswith('.service') and 'WantedBy=multi-user.target' in open(src).read():
                    link = os.path.join(wants, fn)
                    if os.path.lexists(link):
                        os.unlink(link)
                    os.symlink('/etc/systemd/system/' + fn, link)
                    log('installed and enabled ' + rel)
                else:
                    log('installed ' + rel)
        os.makedirs(t.h('var/lib/s9-ubports'), exist_ok=True)
        done = t.h('var/lib/s9-ubports/firstrun.done')
        if os.path.exists(done):
            os.unlink(done)
    print('scrub finished')


# ---- audit -------------------------------------------------------------------------------------
def cmd_audit(a):
    t = Tree(a.tree)
    old = a.old_user
    new = a.expect_user
    block, review = {}, {}

    def add(d, key, item):
        d.setdefault(key, []).append(item)

    rx = None
    if old and old != new:
        rx, _ = user_regex(old)
    # accounts
    for p in t.accounts():
        if p[2].isdigit() and int(p[2]) >= 1000 and p[0] not in ('nobody', new):
            add(block, 'extra human account', p[0])
        if old and p[0] == old and old != new:
            add(block, 'old account still present', '<OLD>')
    for l in open(t.h('etc/shadow'), errors='surrogateescape'):
        f = l.split(':')
        if len(f) > 1 and f[0] != new and f[1] not in ('*', '!', '!!', ''):
            add(block, 'password hash of an account other than the new user', f[0])
    # forbidden paths and non-free packages
    for g in FORBIDDEN_PATHS:
        d, base = os.path.split(g)
        dd = t.h(d) if d else t.root
        if os.path.isdir(dd):
            for e in os.listdir(dd):
                if fnmatch.fnmatch(e, base):
                    add(block, 'forbidden path present', d + '/' + e if d else e)
    for d in ('etc/NetworkManager/system-connections', 'var/lib/bluetooth', 'var/lib/ofono'):
        dd = t.h(d)
        if os.path.isdir(dd) and os.listdir(dd):
            add(block, 'runtime state present', d)
    if os.path.getsize(t.h('etc/machine-id')) != 0:
        add(block, 'machine-id is not empty', 'etc/machine-id')
    st = open(t.h('var/lib/dpkg/status'), errors='surrogateescape').read()
    for pkg in NONFREE_PACKAGES:
        if re.search(r'(?m)^Package: %s$' % re.escape(pkg), st):
            add(block, 'non-free package registered', pkg)
    hal = t.h('var/lib/lxc/android/android-rootfs.img')
    if not os.path.isfile(hal):
        add(block, 'Halium image missing', 'var/lib/lxc/android/android-rootfs.img')
    elif a.halium_sha256:
        h = hashlib.sha256()
        with open(hal, 'rb') as f:
            for chunk in iter(lambda: f.read(8 * MIB), b''):
                h.update(chunk)
        if h.hexdigest() != a.halium_sha256:
            add(block, 'Halium image differs from the documented one', h.hexdigest())
    # one pass over the files
    unowned_by_top = {}
    for top in ('etc', 'usr', 'opt', 'var', 'home', 'root', 'srv', 'boot', 'lib', 'bin', 'sbin'):
        if not os.path.lexists(t.h(top)) or os.path.islink(t.h(top)):
            continue
        for rel, s in walk(t.root, top):
            p = t.h(rel)
            islink = stat.S_ISLNK(s.st_mode)
            if rel.startswith('var/log/') and s.st_size > 0 and not islink:
                add(review, 'log file not empty', rel)
            if not t.interesting(rel):
                continue
            n = norm(rel)
            unowned = n not in t.owned
            if rel.lower().endswith(('.exe', '.msi')) and unowned:
                add(block, 'Windows binary', rel)
            if unowned and not islink and rel.startswith(('usr/', 'lib/', 'opt/', 'srv/', 'boot/', 'var/lib/', 'bin/', 'sbin/')):
                allowed = rel.startswith(ALLOW_UNOWNED) or any(g.search(rel) for g in GENERATED)
                blobby = s.st_size > MIB or rel.lower().endswith(BLOB_EXT) or is_elf(p) or 'firmware' in rel.split('/')
                if not allowed:
                    if blobby and any(fnmatch.fnmatch(rel, g) for g in (a.allow_blob or [])):
                        add(review, 'ALLOWED BLOB: this image is for private tests only, never publish it', '%s (%s)' % (rel, human(s.st_size)))
                    elif blobby:
                        add(block, 'unowned binary/firmware/large file outside the allow-list', '%s (%s)' % (rel, human(s.st_size)))
                    else:
                        k = '/'.join(rel.split('/')[:4])
                        unowned_by_top[k] = unowned_by_top.get(k, 0) + 1
            if islink:
                if rx and rx.search(os.readlink(p)):
                    add(block, 'old user name in a symlink target', rel)
                continue
            if rx and rx.search(rel):
                add(block, 'old user name in a path', '<OLD> path: ' + rx.sub('<OLD>', rel))
            if not stat.S_ISREG(s.st_mode):
                continue
            if s.st_size > 64 * MIB:
                continue
            txt = read_text_file(p, 2 * MIB)
            if txt is None:
                if rx and unowned and is_elf(p) and s.st_size < 64 * MIB:
                    try:
                        data = open(p, 'rb').read()
                    except OSError:
                        continue
                    if re.search(rb'/home/' + re.escape(old.encode()) + rb'(?![A-Za-z0-9])', data):
                        add(review, 'old user name inside a binary', rel)
                continue
            if rx and rx.search(txt):
                add(block, 'old user name in file content', rel)
            if rel in ('etc/shadow', 'etc/gshadow'):
                continue
            for name, pat in SECRET_BLOCK.items():
                if rel == 'etc/shadow':
                    continue
                if pat.search(txt):
                    add(block, 'secret in file: ' + name, rel)
            for name, pat in SECRET_REVIEW.items():
                ms = [m for m in pat.finditer(txt)]
                if name == 'e-mail address':
                    ms = [m for m in ms if not BENIGN_MAIL.search(m.group(0))]
                if name in ('e-mail address', 'MAC address') and (rel.endswith(('.h', '.hpp', '.c', '.cc', '.cpp', '.pc')) or '/include/' in rel):
                    ms = []
                if ms:
                    add(review, name, '%s (%d)' % (rel, len(ms)))
    for nme, c in sorted(opt_references(t).items()):
        if c == 0 and nme.startswith('s9-'):
            add(review, 'unreferenced /opt/s9-* directory (use --prune-opt-unreferenced)', nme)
    for k, v in sorted(unowned_by_top.items()):
        add(review, 'unowned small files not on the allow-list', '%s: %d files' % (k, v))
    # report
    mk = (lambda x: re.sub(r'(?<![A-Za-z0-9])%s(?![A-Za-z0-9])' % re.escape(old), '<OLD>', x)) if old else (lambda x: x)
    lines = []
    for title, d in (('BLOCKING', block), ('REVIEW', review)):
        total = sum(len(v) for v in d.values())
        lines.append('== %s findings: %d' % (title, total))
        for k, v in sorted(d.items()):
            lines.append('  - %s: %d' % (k, len(v)))
            for item in v[:a.limit]:
                lines.append('      ' + mk(item))
            if len(v) > a.limit:
                lines.append('      ... %d more (see the full report)' % (len(v) - a.limit))
    full = []
    for title, d in (('BLOCKING', block), ('REVIEW', review)):
        full.append('== %s' % title)
        for k, v in sorted(d.items()):
            full.append('  - %s: %d' % (k, len(v)))
            full.extend('      ' + mk(i) for i in v)
    if a.report:
        with open(a.report, 'w') as f:
            f.write('\n'.join(full) + '\n')
    print('\n'.join(lines))
    if a.report:
        print('full report: ' + a.report)
    sys.exit(1 if block else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('inventory'); p.add_argument('tree'); p.add_argument('--old-user'); p.set_defaults(fn=cmd_inventory)
    p = sub.add_parser('scrub'); p.add_argument('tree'); p.add_argument('--user', required=True)
    p.add_argument('--old-user'); p.add_argument('--hostname', default='s9'); p.add_argument('--overlay')
    p.add_argument('--keep-home', action='append'); p.add_argument('--drop', action='append')
    p.add_argument('--prune-opt-unreferenced', action='store_true'); p.set_defaults(fn=cmd_scrub)
    p = sub.add_parser('audit'); p.add_argument('tree'); p.add_argument('--old-user')
    p.add_argument('--expect-user', required=True); p.add_argument('--halium-sha256'); p.add_argument('--report')
    p.add_argument('--limit', type=int, default=12); p.add_argument('--allow-blob', action='append'); p.set_defaults(fn=cmd_audit)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
