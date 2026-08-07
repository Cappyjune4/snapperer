<div align="center">

<h1 style="font-size: 3em;">Snapperer</h1>

</div>

A GTK front-end for setting up [snapper](http://snapper.io/) + [grub-btrfs](https://github.com/Antynea/grub-btrfs) on a btrfs root. Works with either the Mint/Ubuntu-desktop `@`/`@home` subvolume layout, or a flat top-level subvolume root (`subvolid=5`, `subvol=/`), as used by curtin/Ubuntu Server autoinstall.

Once set up, every apt transaction gets automatic pre/post snapshots, a timeline of hourly/daily/weekly snapshots is kept and pruned automatically, and the GRUB boot menu grows a "Btrfs snapshots" submenu so you can boot straight into any snapshot if something goes wrong.

## Requirements

- A btrfs root filesystem, already mounted (this doesn't touch partitioning, run it after the OS install is complete)
- GTK 3 + PyGObject (`python3-gi`, usually already installed on GNOME desktops)
- `polkit` (for the `pkexec` authentication prompt)
- Ubuntu/Mint-based (uses `apt`)

## Installation

### Debian/Ubuntu (.deb)

Grab the latest `.deb` from [Releases](../../releases/latest) and install it:

```bash
sudo apt install ./snapperer_*_all.deb
```

This installs a `snapperer` launcher on your PATH and adds it to your applications menu.

### Run from source

```bash
python3 snapperer.py
```

## Usage

The app checks your root filesystem on launch, if it isn't btrfs, the Run button is disabled and it tells you why. Confirm (or override) the user `.snapshots` should be owned by, then click **Run Setup**. That triggers a `pkexec` authentication prompt, then streams the setup's own progress into a live checklist and log as it:

1. Installs `snapper`, `inotify-tools`, `git`, `make`, `gawk`
2. Sets `gawk` as the default `awk` (`mawk` breaks grub-btrfs's UUID parsing)
3. Builds `grub-btrfs` from source (not packaged for Ubuntu/Mint)
4. Creates the snapper `root` config
5. Fixes `.snapshots` permissions
6. Enables the snapper timeline + cleanup timers
7. Enables `grub-btrfsd` (auto-updates the GRUB menu on new snapshots)
8. Regenerates the GRUB config
9. Verifies everything actually took

`setup-snapper-grub-btrfs.sh` also runs standalone (`sudo ./setup-snapper-grub-btrfs.sh`) without the GUI, same as before. The GUI just calls it with an explicit `--target-user=` flag instead of relying on `$SUDO_USER`, since `pkexec` (unlike `sudo`) doesn't set that variable.

Reboot afterward and check the GRUB menu for the "Btrfs snapshots" submenu to confirm.

## License

[GPLv3](LICENSE)
