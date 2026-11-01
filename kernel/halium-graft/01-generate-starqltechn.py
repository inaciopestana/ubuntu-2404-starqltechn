#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


TEXT_EXTS = {
    ".sh", ".py", ".md", ".txt", ".conf", ".service", ".rules",
    ".yaml", ".yml", ".json", ".xml", ".ini", ".desktop",
    ".mk", ".bp", ".rc", ".config", ".list", ".override",
    ".env", ".toml", ".csv", ".tsv", ""
}

SUSPECT = re.compile(
    r"(star2qltechn|star2qlte|G965\w*|Galaxy S9\+)",
    re.I
)

#
# Não entram no enxerto gráfico.
#
PRUNE_TOP = {
    "docs",
    "installer",
    "release",
    "ubuntu-remote",
    "scripts",
}

PRUNE_BASENAMES = {
    "README.md",
}

#
# Subsistemas deliberadamente fora do primeiro bring-up.
#
PRUNE_OVERLAY_RE = re.compile(
    r"(?:^|/)(?:"
    r"camera(?:\.|/)"
    r"|.*audio.*"
    r"|.*pulse.*"
    r"|.*nfc.*"
    r"|.*gps.*"
    r"|.*agnss.*"
    r"|.*mobile-dns.*"
    r"|.*telephony.*"
    r"|.*mobile-data.*"
    r"|.*ofono.*"
    r"|.*ril.*"
    r")",
    re.I
)

#
# Substituições adicionais que só fazemos DEPOIS
# de podar os subsistemas não desejados.
#
EXTRA_REPLACEMENTS = (
    ("star2qltechn", "starqltechn"),
    ("star2qlte", "starqlte"),

    # Esse service é só de permissões de GPU.
    ("star2-gpu-permissions",
     "s9-gpu-permissions"),
    ("99-star2-gpu.rules",
     "99-s9-gpu.rules"),
)


def load_map(path: Path):
    pairs = []

    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue

        a, b, *_ = line.split("\t")
        pairs.append((a, b))

    return pairs


def is_text(path: Path):
    if path.is_symlink():
        return False

    if path.suffix.lower() in TEXT_EXTS:
        return True

    try:
        data = path.read_bytes()[:4096]
        return b"\0" not in data
    except OSError:
        return False


def apply_replacements(text: str, pairs):
    for old, new in pairs:
        text = text.replace(old, new)

    return text


def prune_tree(out: Path):
    #
    # Diretórios inteiros que não fazem parte do enxerto.
    #
    for name in PRUNE_TOP:
        p = out / name

        if not (p.exists() or p.is_symlink()):
            continue

        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()

    #
    # README principal é específico do release S9+.
    #
    for name in PRUNE_BASENAMES:
        p = out / name

        if p.exists() or p.is_symlink():
            p.unlink()

    #
    # Remover apenas subsistemas não-gráficos do overlay.
    #
    overlay = out / "overlay"

    if not overlay.exists():
        return

    victims = []

    for p in overlay.rglob("*"):
        rel = p.relative_to(out).as_posix()

        if PRUNE_OVERLAY_RE.search(rel):
            victims.append(p)

    #
    # Filhos primeiro.
    #
    for p in sorted(
        victims,
        key=lambda x: len(x.parts),
        reverse=True
    ):
        if not (p.exists() or p.is_symlink()):
            continue

        if p.is_dir() and not p.is_symlink():
            try:
                p.rmdir()
            except OSError:
                pass
        else:
            p.unlink()


def rewrite_symlink_targets(out: Path, pairs):
    for p in out.rglob("*"):
        if not p.is_symlink():
            continue

        target = os.readlink(p)
        new_target = apply_replacements(target, pairs)

        if target == new_target:
            continue

        p.unlink()
        p.symlink_to(new_target)


def rename_paths(out: Path, pairs):
    #
    # Mais profundo primeiro para não invalidar caminhos dos filhos.
    #
    paths = sorted(
        list(out.rglob("*")),
        key=lambda p: len(p.parts),
        reverse=True
    )

    for p in paths:
        if not (p.exists() or p.is_symlink()):
            continue

        new_name = apply_replacements(p.name, pairs)

        if new_name == p.name:
            continue

        q = p.with_name(new_name)

        if q.exists() or q.is_symlink():
            raise RuntimeError(
                f"colisão ao renomear:\n"
                f"  {p}\n"
                f"  -> {q}"
            )

        p.rename(q)


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--reference",
        required=True
    )

    ap.add_argument(
        "--output",
        required=True
    )

    ap.add_argument(
        "--map",
        dest="mapfile",
        required=True
    )

    ap.add_argument(
        "--report-dir",
        required=True
    )

    ap.add_argument(
        "--force",
        action="store_true"
    )

    ns = ap.parse_args()

    src = Path(ns.reference).resolve()
    out = Path(ns.output).resolve()
    rep = Path(ns.report_dir).resolve()

    if not src.is_dir():
        ap.error(
            f"referência não existe: {src}"
        )

    if out.exists():
        if not ns.force:
            ap.error(
                f"output já existe: {out}; "
                f"use --force"
            )

        shutil.rmtree(out)

    rep.mkdir(
        parents=True,
        exist_ok=True
    )

    #
    # Crucial: preservar symlinks.
    #
    shutil.copytree(
        src,
        out,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git"
        )
    )

    #
    # Primeiro retiramos tudo que não faz parte
    # do graft gráfico.
    #
    prune_tree(out)

    pairs = (
        load_map(Path(ns.mapfile))
        + list(EXTRA_REPLACEMENTS)
    )

    changed = []

    #
    # Reescrever conteúdo textual.
    #
    for p in out.rglob("*"):
        if (
            not p.is_file()
            or p.is_symlink()
            or not is_text(p)
        ):
            continue

        try:
            raw = p.read_text(
                errors="surrogateescape"
            )
        except Exception:
            continue

        new = apply_replacements(
            raw,
            pairs
        )

        if new != raw:
            p.write_text(
                new,
                errors="surrogateescape"
            )

            changed.append(
                str(
                    p.relative_to(out)
                )
            )

    #
    # Corrigir primeiro os targets dos symlinks,
    # depois os nomes dos arquivos.
    #
    rewrite_symlink_targets(
        out,
        pairs
    )

    rename_paths(
        out,
        pairs
    )

    #
    # Auditoria final:
    # verifica tanto conteúdo quanto nomes de paths.
    #
    unresolved = []

    for p in out.rglob("*"):
        rel = p.relative_to(out).as_posix()

        for m in SUSPECT.finditer(rel):
            unresolved.append(
                f"PATH:{rel}:{m.group(0)}"
            )

        if (
            not p.is_file()
            or p.is_symlink()
            or not is_text(p)
        ):
            continue

        try:
            raw = p.read_text(
                errors="surrogateescape"
            )
        except Exception:
            continue

        for m in SUSPECT.finditer(raw):
            line = (
                raw.count(
                    "\n",
                    0,
                    m.start()
                )
                + 1
            )

            unresolved.append(
                f"TEXT:{rel}:"
                f"{line}:"
                f"{m.group(0)}"
            )

    (
        rep
        / "changed-files.txt"
    ).write_text(
        "\n".join(
            sorted(set(changed))
        )
        + "\n"
    )

    (
        rep
        / "unclassified-identifiers.txt"
    ).write_text(
        (
            "\n".join(unresolved)
            + "\n"
        )
        if unresolved
        else ""
    )

    #
    # Diff ainda útil mesmo com symlinks.
    #
    try:
        result = subprocess.run(
            [
                "diff",
                "-ruN",
                "--no-dereference",
                "--exclude=.git",
                str(src),
                str(out),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        diff = result.stdout

    except FileNotFoundError:
        diff = "diff(1) ausente\n"

    (
        rep
        / "adaptation-diff.patch"
    ).write_text(diff)

    if unresolved:
        print(
            f"PARADA SEGURA: "
            f"{len(unresolved)} ocorrência(s) "
            f"S9+ ainda presentes.\n"
            f"Veja "
            f"{rep/'unclassified-identifiers.txt'}",
            file=sys.stderr
        )

        return 3

    print(
        "Adaptação GRAPHICS-GRAFT "
        f"criada em {out}"
    )

    print(
        "Podados: docs/installer/releases/"
        "Ubuntu Remote e camera/audio/NFC/"
        "GPS/telefonia."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
