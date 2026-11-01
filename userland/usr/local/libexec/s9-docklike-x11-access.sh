#!/bin/bash
# S9_DOCKLIKE_X11_ACCESS_V1
set -Eeuo pipefail

U=@S9_USER@
SOCKET=/tmp/.X11-unix/X0
DIR=/tmp/.X11-unix

echo "===== S9 X11 SOCKET ACCESS ====="

for i in $(seq 1 45); do

    if [ -S "$SOCKET" ] && [ ! -L "$SOCKET" ]; then

        # Permitir atravessar o diretorio, se necessario.
        if ! runuser -u "$U" -- test -x "$DIR"; then
            setfacl -m "u:$U:x" "$DIR"
            echo "X11_DIRECTORY_ACL_FIXED=1"
        fi

        # Permissao somente para o usuario da sessao XFCE.
        setfacl -m "u:$U:rw" "$SOCKET"

        if runuser -u "$U" -- \
            env -u XAUTHORITY DISPLAY=:0 \
            python3 -c '
from Xlib import display
d = display.Display()
print("X11_CONNECTION_SUCCESS=1")
print("ROOT_ID=", hex(d.screen().root.id))
d.close()
' ; then

            echo "X11_SOCKET_ACCESS_OK=1"
            exit 0
        fi

        echo "X11_PROBE_FAILED=$i"

    else
        echo "X11_SOCKET_NOT_READY=$i"
    fi

    sleep 1
done

echo "ERROR=XWAYLAND_NOT_ACCESSIBLE"

ls -ld "$DIR" "$SOCKET" || true
getfacl -p "$SOCKET" || true

exit 1
