#!/usr/bin/env python3

import glob
import os
import pwd
import re
import select
import shutil
import struct
import subprocess
import sys
import time

USER = "@S9_USER@"
HOME = pwd.getpwnam(USER).pw_dir
UID = pwd.getpwnam(USER).pw_uid

SINK = "sink.fast"

EV_KEY = 1
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115

STEP = 5
REPEAT_DELAY = 0.45
REPEAT_INTERVAL = 0.14

ALLOWED_INPUTS = {
    "qpnp_pon",
    "gpio_keys",
}

EVENT = struct.Struct("llHHi")
WORD_BITS = struct.calcsize("L") * 8

RUNUSER = shutil.which("runuser")
PACTL = shutil.which("pactl")

if not RUNUSER or not PACTL:
    raise RuntimeError("runuser ou pactl nao encontrado")


def log(message):
    print(message, flush=True)


def pulse(*args):
    command = [
        RUNUSER,
        "-u", USER,
        "--",
        "/usr/bin/env",
        "HOME=" + HOME,
        "USER=" + USER,
        "XDG_RUNTIME_DIR=/run/user/" + str(UID),
        (
            "PULSE_SERVER=unix:/run/user/"
            + str(UID)
            + "/pulse/native"
        ),
        "PULSE_NO_AUTOSPAWN=1",
        PACTL,
        *args,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
    )

    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "pactl falhou"
        )

    return result.stdout.strip()


def get_volume():
    text = pulse("get-sink-volume", SINK)

    percentages = re.findall(
        r"(\d+)\s*%",
        text,
    )

    if not percentages:
        raise RuntimeError(
            "Nao foi possivel ler o volume: " + text
        )

    return int(percentages[0])


def change_volume(key):
    current = get_volume()

    if key == KEY_VOLUMEUP:
        target = min(100, current + STEP)
        direction = "UP"

    elif key == KEY_VOLUMEDOWN:
        target = max(0, current - STEP)
        direction = "DOWN"

    else:
        return

    if current != target:
        pulse(
            "set-sink-volume",
            SINK,
            str(target) + "%",
        )

    if key == KEY_VOLUMEUP:
        pulse("set-sink-mute", SINK, "0")

    log(
        "VOLUME_{}={}%; ANTES={}%".format(
            direction,
            target,
            current,
        )
    )


def key_capabilities(path):
    with open(path) as f:
        words = f.read().split()

    mask = 0

    for word in words:
        mask = (mask << WORD_BITS) | int(word, 16)

    return mask


def discover_devices():
    devices = {}
    found = {
        KEY_VOLUMEUP: False,
        KEY_VOLUMEDOWN: False,
    }

    for path in sorted(
        glob.glob("/sys/class/input/event*")
    ):
        try:
            with open(path + "/device/name") as f:
                name = f.read().strip()

            if name not in ALLOWED_INPUTS:
                continue

            keys = key_capabilities(
                path + "/device/capabilities/key"
            )

            supported = set()

            for code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN):
                if keys & (1 << code):
                    supported.add(code)
                    found[code] = True

            if supported:
                device = (
                    "/dev/input/" + os.path.basename(path)
                )

                devices[device] = supported

                log(
                    "INPUT={} NAME={} KEYS={}".format(
                        device,
                        name,
                        ",".join(map(str, sorted(supported))),
                    )
                )

        except (OSError, ValueError):
            continue

    if not found[KEY_VOLUMEUP]:
        raise RuntimeError(
            "KEY_VOLUMEUP (115) nao encontrado"
        )

    if not found[KEY_VOLUMEDOWN]:
        raise RuntimeError(
            "KEY_VOLUMEDOWN (114) nao encontrado"
        )

    return devices


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Servico deve executar como root")

    devices = discover_devices()

    if len(sys.argv) == 2 and sys.argv[1] == "--probe":
        log("TECLAS_FISICAS_IDENTIFICADAS=1")

        try:
            log("PULSEAUDIO_VOLUME={}%".format(get_volume()))
        except Exception as error:
            log("PULSEAUDIO_ERRO=" + str(error))

        return

    if len(sys.argv) != 1:
        raise RuntimeError("Argumento desconhecido")

    poller = select.poll()
    fdmap = {}

    for device, supported in devices.items():
        fd = os.open(
            device,
            os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
        )

        fdmap[fd] = (device, supported)
        poller.register(
            fd,
            select.POLLIN |
            select.POLLERR |
            select.POLLHUP
        )

    # Um pressionamento pode vir de cada dispositivo.
    pressed = {}

    log("S9_VOLUME_READY=1")
    log("SINK=" + SINK)
    log("VOLUME_STEP=5_PERCENT")
    log("VOLUME_RANGE=0_TO_100")
    log("HOLD_REPEAT=ENABLED")

    try:
        while True:
            timeout_ms = 100 if pressed else 1000

            for fd, flags in poller.poll(timeout_ms):

                if flags & (
                    select.POLLERR | select.POLLHUP
                ):
                    raise RuntimeError(
                        "Dispositivo de entrada desconectado"
                    )

                if not (flags & select.POLLIN):
                    continue

                try:
                    data = os.read(
                        fd,
                        EVENT.size * 64,
                    )
                except BlockingIOError:
                    continue

                _, supported = fdmap[fd]

                for offset in range(
                    0,
                    len(data),
                    EVENT.size,
                ):
                    chunk = data[
                        offset:offset + EVENT.size
                    ]

                    if len(chunk) != EVENT.size:
                        continue

                    (
                        _sec,
                        _usec,
                        event_type,
                        key,
                        value,
                    ) = EVENT.unpack(chunk)

                    if event_type != EV_KEY:
                        continue

                    if key not in supported:
                        continue

                    item = (fd, key)

                    if value == 1:
                        # Pressionamento inicial.
                        if item in pressed:
                            continue

                        now = time.monotonic()

                        pressed[item] = (
                            now + REPEAT_DELAY,
                            now,
                        )

                        log(
                            "KEY_DOWN={}".format(
                                "UP" if key == KEY_VOLUMEUP
                                else "DOWN"
                            )
                        )

                        try:
                            change_volume(key)
                        except Exception as error:
                            log(
                                "ERRO_PULSEAUDIO="
                                + str(error)
                            )

                    elif value == 0:
                        # Soltou a tecla.
                        pressed.pop(item, None)

                        log(
                            "KEY_UP={}".format(
                                "UP" if key == KEY_VOLUMEUP
                                else "DOWN"
                            )
                        )

                    # value == 2: repeticao do kernel.
                    # Ignorada para evitar ajuste duplicado.

            now = time.monotonic()

            for item, values in list(pressed.items()):
                next_repeat, start = values

                if now < next_repeat:
                    continue

                # Protecao contra tecla presa:
                # nao repetir indefinidamente.
                if now - start > 10:
                    continue

                fd, key = item

                try:
                    change_volume(key)
                except Exception as error:
                    log(
                        "ERRO_PULSEAUDIO="
                        + str(error)
                    )

                pressed[item] = (
                    time.monotonic() + REPEAT_INTERVAL,
                    start,
                )

    finally:
        for fd in fdmap:
            os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log("ERRO_FATAL=" + str(error))
        sys.exit(1)
