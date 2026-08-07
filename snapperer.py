#!/usr/bin/env python3
"""GUI front-end for setup-snapper-grub-btrfs.sh.

Unlike smb-mounter, this doesn't reimplement the script's logic in
Python, the original script already does the real work correctly, so
this just runs it via pkexec (passing --target-user explicitly, since
pkexec doesn't set SUDO_USER the way sudo does) and turns its own
"==> Step N: ..." progress markers into a live checklist.
"""
import getpass
import os
import re
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "setup-snapper-grub-btrfs.sh"
)

# Mirrors the script's own step order. Index 0 has no "Step N:" marker in the
# script (it's the sanity check up front); indices 1-9 match "Step 1".."Step 9".
STEPS = [
    "Sanity check: confirm btrfs root",
    "Install snapper, inotify-tools, git, make, gawk",
    "Set gawk as the default awk",
    "Build grub-btrfs from source",
    "Create snapper root config",
    "Fix .snapshots permissions",
    "Enable snapper timeline + cleanup timers",
    "Enable grub-btrfsd",
    "Regenerate GRUB config",
    "Verify everything",
]

PENDING, RUNNING, DONE, FAILED = "⏳", "\U0001f504", "✅", "❌"

STEP_RE = re.compile(r"^==> Step (\d+):")
SANITY_RE = re.compile(r"^==> Sanity check:")
DONE_RE = re.compile(r"^==> Done\.")


class SnapperBtrfsWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Snapperer")
        self.set_default_size(600, 560)
        self.set_border_width(12)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(root)

        # --- Pre-flight info ---
        self.info_label = Gtk.Label(xalign=0)
        self.info_label.set_line_wrap(True)
        root.pack_start(self.info_label, False, False, 0)

        # --- Target user ---
        user_box = Gtk.Box(spacing=6)
        user_box.pack_start(Gtk.Label(label="Target user (.snapshots owner):"), False, False, 0)
        self.user_entry = Gtk.Entry(text=getpass.getuser())
        user_box.pack_start(self.user_entry, True, True, 0)
        root.pack_start(user_box, False, False, 0)

        # --- Checklist ---
        root.pack_start(Gtk.Label(label="Steps:", xalign=0), False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(220)
        self.step_list = Gtk.ListBox()
        self.step_rows = []
        for step in STEPS:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=8)
            box.set_border_width(4)
            status = Gtk.Label(label=PENDING)
            status.set_width_chars(2)
            box.pack_start(status, False, False, 0)
            box.pack_start(Gtk.Label(label=step, xalign=0), True, True, 0)
            row.add(box)
            self.step_list.add(row)
            self.step_rows.append(status)
        scroller.add(self.step_list)
        root.pack_start(scroller, False, False, 0)

        # --- Run button ---
        self.run_btn = Gtk.Button(label="Run Setup")
        self.run_btn.get_style_context().add_class("suggested-action")
        self.run_btn.connect("clicked", self.on_run_clicked)
        root.pack_start(self.run_btn, False, False, 0)

        # --- Log ---
        root.pack_start(Gtk.Label(label="Log:", xalign=0), False, False, 0)
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_min_content_height(160)
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_buffer = self.log_view.get_buffer()
        log_scroller.add(self.log_view)
        root.pack_start(log_scroller, True, True, 0)

        self.current_step = None
        self.check_root_fs()

    # ---- pre-flight ------------------------------------------------

    def check_root_fs(self):
        try:
            fstype = subprocess.run(
                ["findmnt", "-no", "FSTYPE", "/"], capture_output=True, text=True
            ).stdout.strip()
        except FileNotFoundError:
            fstype = ""

        if fstype == "btrfs":
            subvol = subprocess.run(
                ["findmnt", "-no", "OPTIONS", "/"], capture_output=True, text=True
            ).stdout.strip()
            subvol_match = next(
                (o.split("=", 1)[1] for o in subvol.split(",") if o.startswith("subvol=")),
                "/",
            )
            self.info_label.set_markup(
                f"<b>Root filesystem:</b> btrfs ✓ (subvolume: {GLib.markup_escape_text(subvol_match)})"
            )
            self.run_btn.set_sensitive(True)
        else:
            self.info_label.set_markup(
                f"<b>Root filesystem:</b> {GLib.markup_escape_text(fstype or 'unknown')} "
                "✗ this tool only works on a btrfs root, cannot proceed."
            )
            self.run_btn.set_sensitive(False)

    # ---- helpers ------------------------------------------------------

    def append_log(self, text):
        def _append():
            end = self.log_buffer.get_end_iter()
            self.log_buffer.insert(end, text + "\n")
            self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0, False, 0, 0)
            return False

        GLib.idle_add(_append)

    def set_step_status(self, index, status):
        def _set():
            self.step_rows[index].set_text(status)
            return False

        GLib.idle_add(_set)

    # ---- run ------------------------------------------------------

    def on_run_clicked(self, _button):
        target_user = self.user_entry.get_text().strip()
        if not target_user:
            self.append_log("Target user is required.")
            return

        self.run_btn.set_sensitive(False)
        self.user_entry.set_sensitive(False)
        self.append_log("Requesting authentication to run setup...")
        threading.Thread(target=self._run_worker, args=(target_user,), daemon=True).start()

    def _run_worker(self, target_user):
        self.current_step = 0
        self.set_step_status(0, RUNNING)

        proc = subprocess.Popen(
            ["pkexec", "bash", SCRIPT_PATH, f"--target-user={target_user}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            line = line.rstrip("\n")
            self.append_log(line)

            m = STEP_RE.match(line)
            if m:
                idx = int(m.group(1))
                if self.current_step is not None:
                    self.set_step_status(self.current_step, DONE)
                self.current_step = idx
                self.set_step_status(idx, RUNNING)
            elif SANITY_RE.match(line):
                self.current_step = 0
                self.set_step_status(0, RUNNING)
            elif DONE_RE.match(line) and self.current_step is not None:
                self.set_step_status(self.current_step, DONE)
                self.current_step = None

        proc.wait()

        if proc.returncode == 0:
            if self.current_step is not None:
                self.set_step_status(self.current_step, DONE)
            self.append_log("Setup complete.")
        else:
            if self.current_step is not None:
                self.set_step_status(self.current_step, FAILED)
            self.append_log(f"Failed (exit code {proc.returncode}), see log above.")

        GLib.idle_add(self.run_btn.set_sensitive, True)
        GLib.idle_add(self.user_entry.set_sensitive, True)


def main():
    win = SnapperBtrfsWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
