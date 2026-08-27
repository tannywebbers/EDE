#!/usr/bin/env python3
"""
EDE.py — Contact Fetcher

Paste raw data containing userIds, set a bearer token, and the app
fetches each customer's contacts from the API and lists all phone
numbers.

    contactName
    contactPhone

One block per contact, no dividers.

Double-click to run (or `python EDE.py`). Standard library only
(tkinter, json, urllib) — nothing to install.
"""

import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.request
import urllib.error
import urllib.parse

API_URL = "https://www.kimbo.world/adminApi/system/loan/userContact/app/list"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ede_token")


def load_token():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_token(token):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)


def find_user_ids(data, found=None):
    """Recursively search JSON structure for all 'userId' values."""
    if found is None:
        found = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "userId" and value:
                found.append(str(value))
            else:
                find_user_ids(value, found)
    elif isinstance(data, list):
        for item in data:
            find_user_ids(item, found)
    return found


def fetch_contacts(user_id, token):
    """Call the API for one userId. Returns (contact_list, emergency_list, error_list)."""
    url = f"{API_URL}?userId={user_id}"
    headers = {
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return [], [], [f"HTTP {exc.code} for userId {user_id}"]
    except Exception as exc:
        return [], [], [f"Error for userId {user_id}: {exc}"]

    if body.get("code") != 200:
        return [], [], [f"API error {body.get('code')} for userId {user_id}: {body.get('msg', '')}"]

    data = body.get("data", {})
    contact_list = data.get("contactList", [])
    emergency = data.get("emergencyContact", [])
    return contact_list, emergency, []


def build_report(user_ids, token):
    """Fetch contacts for all userIds and build the text report."""
    blocks = []
    errors = []
    seen = set()

    for uid in user_ids:
        if uid in seen:
            continue
        seen.add(uid)

        contacts, emergency, errs = fetch_contacts(uid, token)
        errors.extend(errs)

        block_lines = []

        self_entry = None
        for c in contacts:
            if c.get("source") == "self":
                self_entry = c
                break

        if self_entry:
            name = (self_entry.get("customerName") or "").strip()
            phone = (self_entry.get("contactNo") or "").strip()
            if name:
                block_lines.append(name)
            if phone:
                block_lines.append(phone)
        elif contacts:
            name = (contacts[0].get("customerName") or "").strip()
            phone = (contacts[0].get("contactNo") or "").strip()
            if name:
                block_lines.append(name)
            if phone:
                block_lines.append(phone)

        for c in contacts:
            if c.get("source") == "self":
                continue
            phone = (c.get("contactNo") or "").strip()
            if phone:
                block_lines.append(phone)

        for ec in emergency:
            phone = (ec.get("contactPhone") or "").strip()
            if phone:
                block_lines.append(phone)

        if block_lines:
            blocks.append("\n".join(block_lines))

    if errors:
        blocks.append("--- ERRORS ---\n" + "\n".join(errors))

    return "\n\n".join(blocks), len(seen), errors


class ContactFetcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Contact Fetcher")
        self.geometry("1100x700")
        self.minsize(800, 500)
        self._build_ui()

    def _build_ui(self):
        token_frame = tk.Frame(self, padx=8, pady=6)
        token_frame.pack(fill="x")

        tk.Label(token_frame, text="Bearer Token:").pack(side="left")
        self.token_var = tk.StringVar(value=load_token())
        self.token_entry = tk.Entry(token_frame, textvariable=self.token_var, show="*", width=60)
        self.token_entry.pack(side="left", padx=4)
        tk.Button(token_frame, text="Toggle Visibility", command=self._toggle_token).pack(side="left", padx=2)
        tk.Button(token_frame, text="Save Token", command=self._save_token).pack(side="left", padx=2)

        toolbar = tk.Frame(self, padx=8, pady=4)
        toolbar.pack(fill="x")

        tk.Button(toolbar, text="Open File", command=self.open_file, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Fetch Contacts", command=self.extract, width=14).pack(side="left", padx=3)
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

        tk.Label(body, text="Paste raw data (JSON with userIds)", anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(body, text="Contacts Output", anchor="w").grid(
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

    def _toggle_token(self):
        current = self.token_entry.cget("show")
        self.token_entry.configure(show="" if current == "*" else "*")

    def _save_token(self):
        save_token(self.token_var.get().strip())
        self.status_var.set("Token saved.")

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Select data file",
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

    def extract(self):
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("No token", "Enter and save a bearer token first.")
            return

        raw = self.input_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("No input", "Paste data or open a file first.")
            return
        try:
            data = json.loads(raw)
        except Exception as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return

        user_ids = find_user_ids(data)
        if not user_ids:
            messagebox.showwarning("No userIds found", "Could not find any userId in the pasted data.")
            return

        unique_ids = list(dict.fromkeys(user_ids))
        self.status_var.set(f"Fetching contacts for {len(unique_ids)} userId(s)...")
        self.update_idletasks()

        report, count, errors = build_report(unique_ids, token)

        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", report)

        if errors:
            self.status_var.set(f"Fetched {count} user(s), {len(errors)} error(s).")
        else:
            self.status_var.set(f"Fetched contacts for {count} user(s).")

    def clear_all(self):
        self.input_text.delete("1.0", "end")
        self.output_text.delete("1.0", "end")
        self.status_var.set("")

    def copy_output(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to copy", "Run Fetch Contacts first.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Copied to clipboard.")

    def save_output(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to save", "Run Fetch Contacts first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save contacts report",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile="contacts_report.txt",
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
    app = ContactFetcherApp()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        try:
            with open(sys.argv[1], "r", encoding="utf-8") as f:
                raw = f.read()
            app.input_text.insert("1.0", raw)
        except Exception:
            pass
    app.mainloop()


if __name__ == "__main__":
    main()
