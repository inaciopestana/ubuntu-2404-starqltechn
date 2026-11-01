#!/usr/bin/env python3

import os
import glob
import time
import fcntl
import select
import struct
import pwd
import tempfile
import subprocess

USER = "@S9_USER@"
UID = pwd.getpwnam(USER).pw_uid
GID = pwd.getpwnam(USER).pw_gid

BACK = "/sys/class/backlight/panel0-backlight"
STATE_DIR = "@S9_HOME@/.local/state/s9-screen"
STATE = STATE_DIR + "/previous-brightness"
LOCK = STATE_DIR + "/toggle.lock"

KEY_POWER = 116
EV_KEY = 1
LONG_PRESS = 3.0

# Linux ARM64: timeval + type + code + value
EVENT = struct.Struct("llHHi")


def log(message):
    print(message, flush=True)


def find_power_event():
    for path in sorted(glob.glob("/sys/class/input/event*")):
        try:
            with open(path + "/device/name") as f:
                name = f.read().strip()

            if name != "qpnp_pon":
                continue

            with open(path + "/device/capabilities/key") as f:
                words = f.read().split()

            mask = 0
            for word in words:
                mask = (mask << 64) | int(word, 16)

            if mask & (1 << KEY_POWER):
                return "/dev/input/" + os.path.basename(path)

        except (OSError, ValueError):
            pass

    raise RuntimeError("qpnp_pon KEY_POWER nao encontrado")


def read_brightness():
    with open(BACK + "/brightness") as f:
        return int(f.read().strip())


def write_brightness(value):
    with open(BACK + "/brightness", "w") as f:
        f.write(str(value) + "\n")


def save_brightness(value):
    fd, tmp = tempfile.mkstemp(
        prefix=".previous-",
        dir=STATE_DIR
    )

    try:
        os.fchown(fd, UID, GID)
        os.fchmod(fd, 0o600)

        with os.fdopen(fd, "w") as f:
            f.write(str(value) + "\n")

        os.replace(tmp, STATE)

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def restore_value(maximum):
    try:
        with open(STATE) as f:
            value = int(f.read().strip())

        if 0 < value <= maximum:
            return value

    except (OSError, ValueError):
        pass

    return min(25500, maximum)



def toggle_screen():
    result = subprocess.run(
        ["/usr/local/sbin/s9-internal-display-power", "toggle"],
        capture_output=True,
        text=True,
        timeout=12
    )

    for line in result.stdout.splitlines():
        log("POWER_CURTO: " + line)

    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or "Falha no controle do AMOLED"
        )


def shutdown():
    log("POWER_LONGO: DESLIGAMENTO_SOLICITADO")

    subprocess.Popen(
        ["/usr/bin/systemctl", "poweroff", "--no-block"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def main():
    device = find_power_event()

    with open(BACK + "/max_brightness") as f:
        maximum = int(f.read().strip())

    if maximum != 50000:
        raise RuntimeError("Backlight inesperado")

    log("S9_POWER_READY=1")
    log("DEVICE=" + device)
    log("SHORT_PRESS=TOGGLE_BACKLIGHT")
    log("LONG_PRESS=3_SECONDS_POWEROFF")

    fd = os.open(
        device,
        os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
    )

    poller = select.poll()
    poller.register(
        fd,
        select.POLLIN | select.POLLERR | select.POLLHUP
    )

    pressed_at = None
    long_handled = False

    while True:
        events = poller.poll(
            100 if pressed_at is not None else 1000
        )

        for _, flags in events:

            if flags & (select.POLLERR | select.POLLHUP):
                raise RuntimeError("Dispositivo Power desconectado")

            if not (flags & select.POLLIN):
                continue

            data = os.read(fd, EVENT.size * 32)

            for offset in range(0, len(data), EVENT.size):
                chunk = data[offset:offset + EVENT.size]

                if len(chunk) != EVENT.size:
                    continue

                _, _, ev_type, code, value = EVENT.unpack(chunk)

                if ev_type != EV_KEY or code != KEY_POWER:
                    continue

                if value == 1:
                    if pressed_at is None:
                        pressed_at = time.monotonic()
                        long_handled = False
                        log("POWER_DOWN")

                elif value == 0:
                    if pressed_at is None:
                        continue

                    duration = time.monotonic() - pressed_at

                    log(f"POWER_UP duration={duration:.2f}s")

                    if not long_handled:
                        if duration >= LONG_PRESS:
                            shutdown()
                        else:
                            try:
                                toggle_screen()
                            except Exception as e:
                                log(f"ERRO_TOGGLE={e}")

                    pressed_at = None
                    long_handled = False

        if pressed_at is not None and not long_handled:

            duration = time.monotonic() - pressed_at

            if duration >= LONG_PRESS:
                long_handled = True
                shutdown()


if __name__ == "__main__":
    main()
