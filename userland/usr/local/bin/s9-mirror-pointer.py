#!/usr/bin/python3

import sys
import time
from evdev import UInput, ecodes as e

INT32_MIN = -2147483648

LOG_W = 2960
LOG_H = 1440

GAIN_X = 2.0
GAIN_Y = 2.0


# ============================================================
# CAPACIDADES
# ============================================================

# Inclui praticamente todas as teclas de teclado Linux.
keyboard_keys = [
    code for name, code in e.ecodes.items()
    if name.startswith("KEY_")
    and isinstance(code, int)
    and 0 < code < e.KEY_MAX
]

caps = {
    e.EV_KEY: sorted(set(
        keyboard_keys + [
            e.BTN_LEFT,
            e.BTN_MIDDLE,
            e.BTN_RIGHT,
        ]
    )),

    e.EV_REL: [
        e.REL_X,
        e.REL_Y,
        e.REL_WHEEL,
        e.REL_HWHEEL,
    ],
}


buttons = {
    1: e.BTN_LEFT,
    2: e.BTN_MIDDLE,
    3: e.BTN_RIGHT,
}


ui = UInput(
    caps,
    name="S9 Mirror Virtual Input",
    bustype=e.BUS_USB,
)

time.sleep(0.5)


# ============================================================
# MOUSE
# ============================================================

def sync_absolute(x, y):

    x = max(0, min(LOG_W - 1, int(x)))
    y = max(0, min(LOG_H - 1, int(y)))

    ui.write(
        e.EV_REL,
        e.REL_X,
        INT32_MIN
    )

    ui.write(
        e.EV_REL,
        e.REL_Y,
        INT32_MIN
    )

    ui.syn()

    ui.write(
        e.EV_REL,
        e.REL_X,
        round(x / GAIN_X)
    )

    ui.write(
        e.EV_REL,
        e.REL_Y,
        round(y / GAIN_Y)
    )

    ui.syn()


def move_relative(dx, dy):

    dx = int(dx)
    dy = int(dy)

    if dx:
        ui.write(
            e.EV_REL,
            e.REL_X,
            dx
        )

    if dy:
        ui.write(
            e.EV_REL,
            e.REL_Y,
            dy
        )

    if dx or dy:
        ui.syn()


# ============================================================
# LOOP
# ============================================================

for line in sys.stdin:

    try:

        p = line.strip().split()

        if not p:
            continue

        cmd = p[0]


        # ----------------------------------------------------
        # SINCRONIZAÇÃO DO MOUSE
        # ----------------------------------------------------

        if cmd == "S":

            sync_absolute(
                int(p[1]),
                int(p[2])
            )


        # ----------------------------------------------------
        # MOVIMENTO RELATIVO
        # ----------------------------------------------------

        elif cmd == "R":

            move_relative(
                int(p[1]),
                int(p[2])
            )


        # ----------------------------------------------------
        # BOTÃO DO MOUSE DOWN
        # ----------------------------------------------------

        elif cmd == "D":

            ui.write(
                e.EV_KEY,
                buttons[int(p[1])],
                1
            )

            ui.syn()


        # ----------------------------------------------------
        # BOTÃO DO MOUSE UP
        # ----------------------------------------------------

        elif cmd == "U":

            ui.write(
                e.EV_KEY,
                buttons[int(p[1])],
                0
            )

            ui.syn()


        # ----------------------------------------------------
        # SCROLL
        # ----------------------------------------------------

        elif cmd == "W":

            dx = int(p[1])
            dy = int(p[2])

            if dx:
                ui.write(
                    e.EV_REL,
                    e.REL_HWHEEL,
                    dx
                )

            if dy:
                ui.write(
                    e.EV_REL,
                    e.REL_WHEEL,
                    dy
                )

            ui.syn()


        # ----------------------------------------------------
        # TECLADO DOWN
        #
        # Recebe keycode EVDEV, não keysym X11.
        # ----------------------------------------------------

        elif cmd == "KD":

            code = int(p[1])

            ui.write(
                e.EV_KEY,
                code,
                1
            )

            ui.syn()


        # ----------------------------------------------------
        # TECLADO UP
        # ----------------------------------------------------

        elif cmd == "KU":

            code = int(p[1])

            ui.write(
                e.EV_KEY,
                code,
                0
            )

            ui.syn()


    except Exception as exc:

        print(
            f"input error: {exc}",
            file=sys.stderr,
            flush=True
        )


ui.close()
