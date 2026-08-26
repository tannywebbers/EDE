#!/usr/bin/env python3
"""
EDE.py — Phone Extractor

Reads the loan-collection JSON dump (top-level "rows" list) and produces
a per-customer report:

    ============================
    CUSTOMER NAME
    ============================
    <customer's own phone>
    <contact 1 phone>
    <contact 2 phone>

    ============================
    NEXT CUSTOMER
    ============================
    ...

One block per record in "rows" — grouped by that record's own
customerName, never merged across different customers or apps.

Double-click to run (or `python EDE.py`). Standard library only
(tkinter, json) — nothing to install.
"""

import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox


def extract_report(data):
    """
    Build the text report. Returns (report_text, record_count).
    Accepts either {"rows": [...]} or a bare list of row objects.
    """
    if isinstance(data, dict):
        rows = data.get("rows", [])
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    blocks = []
    for row in rows:
        customer_name = (row.get("customerName") or "").strip()
        customer_phone = (row.get("phone") or "").strip()
        contacts = row.get("contactList") or []

        numbers = []
        if customer_phone:
            numbers.append(customer_phone)

        # Dedupe contact numbers for THIS customer only, preserve order.
        seen = set(numbers)
        for contact in contacts:
            contact_phone = (contact.get("contactNo") or "").strip()
            if contact_phone and contact_phone not in seen:
                numbers.append(contact_phone)
                seen.add(contact_phone)

        header = customer_name if customer_name else "(no name)"
        divider = "=" * max(len(header), 12)
        block_lines = [divider, header, divider]
        block_lines.extend(numbers if numbers else ["(no numbers found)"])
        blocks.append("\n".join(block_lines))

    report = "\n\n".join(blocks)
    return report, len(rows)


class PhoneExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Phone Extractor")
        self.geometry("1100x650")
        self.minsize(800, 450)
        self._build_ui()

    def _build_ui(self):
        toolbar = tk.Frame(self, padx=8, pady=6)
        toolbar.pack(fill="x")

        tk.Button(toolbar, text="Open File", command=self.open_file, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Extract", command=self.extract, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Clear", command=self.clear_all, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Copy Output", command=self.copy_output, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Save Output", command=self.save_output, width=12).pack(side="left", padx=3)

        self.status_var = tk.StringVar(value="")
        tk.Label(toolbar, textvariable=self.status_var, anchor="e").pack(side="right", padx=6)

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        tk.Label(body, text="Paste JSON here, or Open File to load a .json dump", anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(body, text="Extraction Report", anchor="w").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        left_frame = tk.Frame(body)
        left_frame.grid(row=1, column=0, sticky="nsew")
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        self.input_text = tk.Text(left_frame, wrap="none", undo=True)
        left_vsb = tk.Scrollbar(left_frame, orient="vertical", command=self.input_text.yview)
        left_hsb = tk.Scrollbar(left_frame, orient="horizontal", command=self.input_text.xview)
        self.input_text.configure(yscrollcommand=left_vsb.set, xscrollcommand=left_hsb.set)
        self.input_text.grid(row=0, column=0, sticky="nsew")
        left_vsb.grid(row=0, column=1, sticky="ns")
        left_hsb.grid(row=1, column=0, sticky="ew")

        right_frame = tk.Frame(body)
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        right_frame.rowconfigure(0, weight=1)
        right_frame.columnconfigure(0, weight=1)

        self.output_text = tk.Text(right_frame, wrap="none", state="normal")
        right_vsb = tk.Scrollbar(right_frame, orient="vertical", command=self.output_text.yview)
        right_hsb = tk.Scrollbar(right_frame, orient="horizontal", command=self.output_text.xview)
        self.output_text.configure(yscrollcommand=right_vsb.set, xscrollcommand=right_hsb.set)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        right_vsb.grid(row=0, column=1, sticky="ns")
        right_hsb.grid(row=1, column=0, sticky="ew")

    # ------------------------------------------------------------------
    def open_file(self):
        path = filedialog.askopenfilename(
            title="Select JSON dump",
            filetypes=[("JSON / text files", "*.json *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as exc:
            messagebox.showerror("Failed to read file", str(exc))
            return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", raw)
        self.status_var.set(f"Loaded {os.path.basename(path)}")
        self.extract()

    def extract(self):
        raw = self.input_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("No input", "Paste JSON or open a file first.")
            return
        try:
            data = json.loads(raw)
        except Exception as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return

        try:
            report, count = extract_report(data)
        except Exception as exc:
            messagebox.showerror("Extraction failed", str(exc))
            return

        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", report)
        self.status_var.set(f"Extracted {count} record(s).")

    def clear_all(self):
        self.input_text.delete("1.0", "end")
        self.output_text.delete("1.0", "end")
        self.status_var.set("")

    def copy_output(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to copy", "Run Extract first.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Copied to clipboard.")

    def save_output(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to save", "Run Extract first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save extraction report",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile="extraction_report.txt",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:
            messagebox.showerror("Failed to save", str(exc))
            return
        messagebox.showinfo("Saved", f"Saved to {path}")


def main():
    app = PhoneExtractorApp()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        try:
            with open(sys.argv[1], "r", encoding="utf-8") as f:
                raw = f.read()
            app.input_text.insert("1.0", raw)
            app.extract()
        except Exception:
            pass
    app.mainloop()


if __name__ == "__main__":
    main()
