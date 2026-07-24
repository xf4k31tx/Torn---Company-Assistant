from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.checksum import (
    load_expected_sha256,
    normalize_sha256,
    sha256_file,
)


def verify_file(
    file_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    expected_sha256: str | None = None,
) -> tuple[bool, str, str]:
    target = Path(file_path)
    if not target.is_file():
        raise ValueError(f"File not found: {target}")
    if (manifest_path is None) == (expected_sha256 is None):
        raise ValueError("Provide exactly one checksum manifest or expected SHA-256 value.")

    expected = (
        load_expected_sha256(manifest_path, target.name)
        if manifest_path is not None
        else normalize_sha256(expected_sha256 or "")
    )
    calculated = sha256_file(target)
    return calculated == expected, expected, calculated


class ChecksumVerifier(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=18)
        self.file_var = tk.StringVar()
        self.manifest_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select the application and its .sha256 file.")
        self.expected_var = tk.StringVar(value="—")
        self.calculated_var = tk.StringVar(value="—")
        self._build()

    def _build(self) -> None:
        self.grid(sticky="nsew")
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="TCA File Integrity Verifier", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )
        ttk.Label(self, text="Application file").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(self, textvariable=self.file_var).grid(row=1, column=1, sticky="ew")
        ttk.Button(self, text="Browse…", command=self._choose_file).grid(
            row=1, column=2, padx=(8, 0)
        )

        ttk.Label(self, text="Checksum file").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0)
        )
        ttk.Entry(self, textvariable=self.manifest_var).grid(
            row=2, column=1, sticky="ew", pady=(10, 0)
        )
        ttk.Button(self, text="Browse…", command=self._choose_manifest).grid(
            row=2, column=2, padx=(8, 0), pady=(10, 0)
        )

        self.verify_button = ttk.Button(self, text="Verify File", command=self._start_verification)
        self.verify_button.grid(row=3, column=0, columnspan=3, pady=18)

        self.status_label = ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="center",
            font=("Segoe UI", 11, "bold"),
        )
        self.status_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        ttk.Label(self, text="Expected SHA-256").grid(row=5, column=0, sticky="nw", padx=(0, 8))
        ttk.Label(
            self, textvariable=self.expected_var, font=("Consolas", 9), wraplength=510
        ).grid(row=5, column=1, columnspan=2, sticky="w")
        ttk.Label(self, text="Calculated SHA-256").grid(
            row=6, column=0, sticky="nw", padx=(0, 8), pady=(8, 0)
        )
        ttk.Label(
            self, textvariable=self.calculated_var, font=("Consolas", 9), wraplength=510
        ).grid(row=6, column=1, columnspan=2, sticky="w", pady=(8, 0))

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select the application to verify",
            filetypes=[("Applications", "*.exe"), ("All files", "*.*")],
        )
        if not selected:
            return
        self.file_var.set(selected)
        target = Path(selected)
        for candidate in (Path(f"{target}.sha256"), target.with_suffix(".sha256")):
            if candidate.is_file():
                self.manifest_var.set(str(candidate))
                break

    def _choose_manifest(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select the SHA-256 checksum file",
            filetypes=[("SHA-256 checksum", "*.sha256"), ("All files", "*.*")],
        )
        if selected:
            self.manifest_var.set(selected)

    def _start_verification(self) -> None:
        file_path = self.file_var.get().strip()
        manifest_path = self.manifest_var.get().strip()
        if not file_path or not manifest_path:
            messagebox.showerror("Missing file", "Select both the application and checksum file.")
            return

        self.verify_button.configure(state="disabled")
        self.status_var.set("Calculating SHA-256…")
        self.status_label.configure(foreground="#555555")
        self.expected_var.set("—")
        self.calculated_var.set("—")
        threading.Thread(
            target=self._verify_worker,
            args=(file_path, manifest_path),
            daemon=True,
        ).start()

    def _verify_worker(self, file_path: str, manifest_path: str) -> None:
        try:
            result = verify_file(file_path, manifest_path=manifest_path)
        except (OSError, ValueError) as exc:
            self.after(0, self._show_error, str(exc))
            return
        self.after(0, self._show_result, *result)

    def _show_result(self, intact: bool, expected: str, calculated: str) -> None:
        self.verify_button.configure(state="normal")
        self.expected_var.set(expected.upper())
        self.calculated_var.set(calculated.upper())
        if intact:
            self.status_var.set("✓ VERIFIED — The file is intact.")
            self.status_label.configure(foreground="#16713a")
        else:
            self.status_var.set("✗ FAILED — The file is altered, damaged, or not the expected release.")
            self.status_label.configure(foreground="#a32020")

    def _show_error(self, error: str) -> None:
        self.verify_button.configure(state="normal")
        self.status_var.set("Verification could not be completed.")
        self.status_label.configure(foreground="#a32020")
        messagebox.showerror("Verification error", error)


def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify a file against a SHA-256 checksum.")
    parser.add_argument("file", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--checksum-file", type=Path)
    source.add_argument("--expected")
    args = parser.parse_args(argv)

    try:
        intact, expected, calculated = verify_file(
            args.file,
            manifest_path=args.checksum_file,
            expected_sha256=args.expected,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Expected:   {expected.upper()}")
    print(f"Calculated: {calculated.upper()}")
    print("VERIFIED" if intact else "FAILED")
    return 0 if intact else 1


def launch() -> None:
    root = tk.Tk()
    root.title("TCA File Integrity Verifier")
    root.geometry("720x330")
    root.minsize(620, 300)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    ChecksumVerifier(root)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(run_cli(sys.argv[1:]))
    launch()
