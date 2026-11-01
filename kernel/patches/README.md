# Kernel patches

Three patches on top of Samsung's sdm845 4.9 kernel, as maintained by FakeShell:

| | |
|---|---|
| Source | https://github.com/FakeShell/android_kernel_samsung_sdm845, branch `ubports` (Linux 4.9.186) |
| Base commit | `a22a0b358140d5c72b8567fb05489bfff2a36948` |
| Config | `starqlte_chn_halium_defconfig` + [`../halium.config`](../halium.config) |

| Patch | What it does |
|---|---|
| `0001-msm-vidc-fix-hevc-profile-control.patch` | The hardware HEVC encoder rejected its own profile control (wrong minimum, menu out of enum order), so the encoder instance failed to open. |
| `0002-bluetooth-build-rfcomm-bnep-hidp.patch` | Samsung commented RFCOMM, BNEP and HIDP out of `net/bluetooth/Makefile`; this builds them again. |
| `0003-msm-dp-ultrawide-3840x1080-and-no-hdcp.patch` | 32:9 3840x1080 over DisplayPort (see [`docs/display-ultrawide.md`](../../docs/display-ultrawide.md)), module parameter `s9_uw_hz`, and HDCP disabled on DisplayPort. |

`build-tools/` holds a patch for the Halium boot-image build scripts (not for the kernel): it keeps Samsung's
`second_addr` in the boot header.

## Checked

Each patch was regenerated from `git diff` of the author's kernel tree and applied to a clean export of the base commit
with `git apply`: it applies without fuzz, and the resulting files equal the author's tree except for comments and
log messages that were translated to English for publication.

## Apply

```sh
git clone --branch ubports https://github.com/FakeShell/android_kernel_samsung_sdm845
cd android_kernel_samsung_sdm845
git checkout a22a0b358140
for p in /path/to/kernel/patches/000*.patch; do git apply "$p" || break; done
```

The kernel is GPL-2.0 only; so are these patches.
