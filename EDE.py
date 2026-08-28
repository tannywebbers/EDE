#!/usr/bin/env python3
"""
EDE.py — Collection Workbench

Two modes (toggle top-right, GET is default):

GET mode — Contact extraction
    Paste a dump of raw JSON (one or many objects) containing userIds.
    The app finds every userId and calls the contacts API for each,
    producing one block per user:

        customerName
        customer own phone
        contact phones (numbers only)
        emergency phones (numbers only)

POST mode — Bulk actions on orders
    Paste the same dump; the app finds every orderNum. Then:
      * Send SMS  -> picks Template 1 or 2, sends to every order, logs
                     "SMS SENT <orderNum>" / "FAILED SMS <orderNum>: ..."
      * Add Report-> posts a collection record per order using the
                     editable fields below.

Double-click to run (or `python EDE.py`). Standard library only
(tkinter, json, urllib, threading, queue).
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.request
import urllib.error

CONTACT_URL = "https://www.kimbo.world/adminApi/system/loan/userContact/app/list"
SMS_URL = "https://www.kimbo.world/adminApi/system/loan/collectionAssign/sendSms"
REPORT_URL = "https://www.kimbo.world/adminApi/system/loan/collectionRecord"

TEMPLATE_1 = "2057421681597583361"
TEMPLATE_2 = "2062494888535728129"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ede_token")


# ----------------------------------------------------------------------
# Token persistence
def load_token():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def save_token(token):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)


# ----------------------------------------------------------------------
# Raw-data parsing (handles several concatenated JSON objects)
def parse_json_dump(raw):
    """Parse one or more back-to-back JSON objects from pasted text."""
    decoder = json.JSONDecoder()
    idx, n = 0, len(raw)
    objects = []
    while idx < n:
        while idx < n and raw[idx] in " \t\r\n":
            idx += 1
        if idx >= n:
            break
        try:
            obj, idx = decoder.raw_decode(raw, idx)
            objects.append(obj)
        except Exception:
            idx += 1
    return objects


def collect_records(objects):
    """Flatten parsed objects into a list of row records."""
    records = []
    for obj in objects:
        if isinstance(obj, dict) and isinstance(obj.get("rows"), list):
            records.extend(r for r in obj["rows"] if isinstance(r, dict))
        elif isinstance(obj, dict):
            records.append(obj)
        elif isinstance(obj, list):
            records.extend(collect_records(obj))
    return records


def extract_user_ids(objects):
    ids = []
    for rec in collect_records(objects):
        uid = rec.get("userId")
        if uid:
            ids.append(str(uid))
    return ids


def extract_orders(objects):
    orders = []
    for rec in collect_records(objects):
        order_num = rec.get("orderNum")
        if order_num:
            orders.append({
                "orderNum": str(order_num),
                "country": (rec.get("country") or "NG").strip(),
                "appName": (rec.get("appName") or "").strip(),
                "customerName": (rec.get("customerName") or "").strip(),
                "phone": (rec.get("phone") or "").strip(),
            })
    return orders


# ----------------------------------------------------------------------
# HTTP helper
def http_request(method, url, token, payload=None):
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, str(exc)


# ----------------------------------------------------------------------
# GET mode: fetch contacts
def fetch_contacts(user_id, token):
    url = f"{CONTACT_URL}?userId={user_id}"
    headers = {"Authorization": f"Bearer {token}"}
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
    return data.get("contactList", []), data.get("emergencyContact", []), []


def format_user_block(user_id, contacts, emergency):
    lines = []
    self_entry = next((c for c in contacts if c.get("source") == "self"), None)
    if self_entry:
        name = (self_entry.get("customerName") or "").strip()
        phone = (self_entry.get("contactNo") or "").strip()
        if name:
            lines.append(name)
        if phone:
            lines.append(phone)
    elif contacts:
        name = (contacts[0].get("customerName") or "").strip()
        phone = (contacts[0].get("contactNo") or "").strip()
        if name:
            lines.append(name)
        if phone:
            lines.append(phone)

    for c in contacts:
        if c.get("source") == "self":
            continue
        phone = (c.get("contactNo") or "").strip()
        if phone:
            lines.append(phone)

    for ec in emergency:
        phone = (ec.get("contactPhone") or "").strip()
        if phone:
            lines.append(phone)

    return "\n".join(lines)


# ----------------------------------------------------------------------
class CollectionWorkbench(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Collection Workbench")
        self.geometry("1150x750")
        self.minsize(820, 560)

        self.events = queue.Queue()
        self.busy = False

        self._build_ui()
        self._pack_get()
        self.after(100, self._process_events)

    def _build_ui(self):
        top = tk.Frame(self, padx=8, pady=6)
        top.pack(fill="x")

        tk.Label(top, text="Bearer Token:").pack(side="left")
        self.token_var = tk.StringVar(value=load_token())
        self.token_entry = tk.Entry(top, textvariable=self.token_var, show="*", width=52)
        self.token_entry.pack(side="left", padx=4)
        tk.Button(top, text="Show", command=self._toggle_token, width=6).pack(side="left", padx=2)
        tk.Button(top, text="Save Token", command=self._save_token).pack(side="left", padx=2)

        tk.Label(top, text="Mode:").pack(side="right", padx=(8, 2))
        self.mode_var = tk.StringVar(value="get")
        tk.Radiobutton(
            top, text=" POST ", variable=self.mode_var, value="post",
            command=self._switch_mode, indicatoron=False
        ).pack(side="right", padx=1)
        tk.Radiobutton(
            top, text=" GET ", variable=self.mode_var, value="get",
            command=self._switch_mode, indicatoron=False
        ).pack(side="right", padx=1)

        toolbar = tk.Frame(self, padx=8, pady=4)
        toolbar.pack(fill="x")
        tk.Button(toolbar, text="Open File", command=self.open_file, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Clear", command=self.clear_all, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Copy Output", command=self.copy_output, width=12).pack(side="left", padx=3)
        tk.Button(toolbar, text="Save Output", command=self.save_output, width=12).pack(side="left", padx=3)

        self.status_var = tk.StringVar(value="")
        tk.Label(toolbar, textvariable=self.status_var, anchor="e").pack(side="right", padx=6)

        self.get_frame = tk.Frame(self)
        self.post_frame = tk.Frame(self)
        self._build_get_frame(self.get_frame)
        self._build_post_frame(self.post_frame)

    # ---- GET panel -----------------------------------------------------
    def _build_get_frame(self, parent):
        action = tk.Frame(parent, padx=8, pady=4)
        action.pack(fill="x")
        tk.Label(action, text="Paste raw JSON (one or many objects) containing userIds").pack(side="left")
        tk.Button(action, text="Fetch Contacts", command=self.fetch_get, width=14).pack(side="right")

        body = tk.Frame(parent)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        tk.Label(body, text="Raw Data").grid(row=0, column=0, sticky="w")
        tk.Label(body, text="Contacts Output").grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.get_input = self._make_text(body, row=1, column=0)
        self.get_output = self._make_text(body, row=1, column=1, padx=(8, 0))

    def _make_text(self, parent, row, column, padx=0):
        frame = tk.Frame(parent)
        frame.grid(row=row, column=column, sticky="nsew", padx=padx)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, wrap="none", undo=True)
        vsb = tk.Scrollbar(frame, orient="vertical", command=text.yview)
        hsb = tk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        return text

    # ---- POST panel ----------------------------------------------------
    def _build_post_frame(self, parent):
        toprow = tk.Frame(parent, padx=8, pady=4)
        toprow.pack(fill="x")
        tk.Label(toprow, text="Paste raw JSON; orderNums are pulled from it").pack(side="left")

        body = tk.Frame(parent)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=3)
        body.rowconfigure(4, weight=2)

        tk.Label(body, text="Raw Data").grid(row=0, column=0, sticky="nsew", pady=(0, 2))
        self.post_input = self._make_text(body, row=1, column=0)

        controls = self._build_post_controls(body)
        controls.grid(row=2, column=0, sticky="ew", pady=4)

        tk.Label(body, text="Output Log").grid(row=3, column=0, sticky="w")
        self.post_output = self._make_text(body, row=4, column=0)

    def _build_post_controls(self, parent):
        ctrl = tk.LabelFrame(parent, text="POST Actions", padx=8, pady=6)

        sms_row = tk.Frame(ctrl)
        sms_row.pack(fill="x", pady=4)
        tk.Label(sms_row, text="SMS Template:").pack(side="left")
        self.template_var = tk.StringVar(value=TEMPLATE_1)
        tk.Radiobutton(
            sms_row, text="Template 1", variable=self.template_var,
            value=TEMPLATE_1
        ).pack(side="left", padx=4)
        tk.Radiobutton(
            sms_row, text="Template 2", variable=self.template_var,
            value=TEMPLATE_2
        ).pack(side="left", padx=4)
        tk.Button(sms_row, text="Send SMS to All Orders", command=self.send_sms).pack(side="left", padx=10)

        grid = tk.Frame(ctrl)
        grid.pack(fill="x", pady=4)

        tk.Label(grid, text="Reach Out By:").grid(row=0, column=0, sticky="e")
        self.reach_out_by = ttk.Combobox(grid, values=["Phone", "SMS", "Email", "Other"], width=12)
        self.reach_out_by.set("Phone")
        self.reach_out_by.grid(row=0, column=1, padx=2, pady=2)

        tk.Label(grid, text="Contact Relations:").grid(row=0, column=2, sticky="e")
        self.contact_relations = ttk.Combobox(
            grid, values=["Self", "Father/Mother", "Sister/Brother", "Friend", "Other"], width=16
        )
        self.contact_relations.set("Self")
        self.contact_relations.grid(row=0, column=3, padx=2, pady=2)

        tk.Label(grid, text="Contact Result:").grid(row=0, column=4, sticky="e")
        self.contact_result = ttk.Combobox(
            grid, values=["No Reply", "Answered", "No Answer", "Wrong Number", "Busy"], width=14
        )
        self.contact_result.set("No Reply")
        self.contact_result.grid(row=0, column=5, padx=2, pady=2)

        tk.Label(grid, text="Collection Tag:").grid(row=1, column=0, sticky="e")
        self.collection_tag = tk.Entry(grid, width=16)
        self.collection_tag.insert(0, "No Answer")
        self.collection_tag.grid(row=1, column=1, padx=2, pady=2)

        tk.Label(grid, text="Contact Name:").grid(row=1, column=2, sticky="e")
        self.contact_name = tk.Entry(grid, width=18)
        self.contact_name.grid(row=1, column=3, padx=2, pady=2)

        tk.Label(grid, text="Contact No:").grid(row=1, column=4, sticky="e")
        self.contact_no = tk.Entry(grid, width=14)
        self.contact_no.grid(row=1, column=5, padx=2, pady=2)

        tk.Label(grid, text="Remark:").grid(row=2, column=0, sticky="e")
        self.remark = tk.Entry(grid, width=34)
        self.remark.grid(row=2, column=1, columnspan=4, padx=2, pady=2, sticky="w")

        tk.Button(grid, text="Add Report to All Orders", command=self.add_report).grid(
            row=2, column=5, padx=4, pady=2
        )

        return ctrl

    # ---- Mode switching ------------------------------------------------
    def _pack_get(self):
        self.post_frame.pack_forget()
        self.get_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _pack_post(self):
        self.get_frame.pack_forget()
        self.post_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _switch_mode(self):
        if self.mode_var.get() == "get":
            self._pack_get()
        else:
            self._pack_post()

    # ---- Token helpers -------------------------------------------------
    def _toggle_token(self):
        current = self.token_entry.cget("show")
        self.token_entry.configure(show="" if current == "*" else "*")

    def _save_token(self):
        save_token(self.token_var.get().strip())
        self.status_var.set("Token saved.")

    # ---- Shared actions -------------------------------------------------
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
        self.active_input().delete("1.0", "end")
        self.active_input().insert("1.0", raw)
        self.status_var.set(f"Loaded {os.path.basename(path)}")

    def clear_all(self):
        for w in (self.get_input, self.get_output, self.post_input, self.post_output):
            w.delete("1.0", "end")
        self.status_var.set("")

    def copy_output(self):
        text = self.active_output().get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to copy", "Run an action first.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Copied to clipboard.")

    def save_output(self):
        text = self.active_output().get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to save", "Run an action first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save report",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile="report.txt",
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

    def active_input(self):
        return self.get_input if self.mode_var.get() == "get" else self.post_input

    def active_output(self):
        return self.get_output if self.mode_var.get() == "get" else self.post_output

    # ---- Event loop bridge to worker threads ---------------------------
    def _process_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "append":
                    self.post_output.insert("end", value)
                    self.post_output.see("end")
                elif kind == "set_output":
                    self.get_output.delete("1.0", "end")
                    self.get_output.insert("1.0", value)
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "clear_post":
                    self.post_output.delete("1.0", "end")
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    # ---- GET action ----------------------------------------------------
    def fetch_get(self):
        if self.busy:
            return
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("No token", "Enter and save a bearer token first.")
            return
        raw = self.get_input.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("No input", "Paste data or open a file first.")
            return

        objects = parse_json_dump(raw)
        user_ids = list(dict.fromkeys(extract_user_ids(objects)))
        if not user_ids:
            messagebox.showwarning("No userIds", "Could not find any userId in the pasted data.")
            return

        self.busy = True
        self.status_var.set(f"Fetching contacts for {len(user_ids)} user(s)...")
        threading.Thread(target=self._worker_get, args=(user_ids, token), daemon=True).start()

    def _worker_get(self, user_ids, token):
        blocks = []
        errors = []
        seen = set()
        for uid in user_ids:
            if uid in seen:
                continue
            seen.add(uid)
            contacts, emergency, errs = fetch_contacts(uid, token)
            errors.extend(errs)
            block = format_user_block(uid, contacts, emergency)
            if block:
                blocks.append(block)

        if errors:
            blocks.append("--- ERRORS ---\n" + "\n".join(errors))
        if not blocks:
            blocks.append("(no results)")

        self.events.put(("set_output", "\n\n".join(blocks)))
        msg = f"Fetched {len(seen)} user(s)" + (f", {len(errors)} error(s)" if errors else "")
        self.events.put(("status", msg))
        self.busy = False

    # ---- POST actions --------------------------------------------------
    def _prepare_orders(self):
        raw = self.post_input.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("No input", "Paste data or open a file first.")
            return None
        objects = parse_json_dump(raw)
        orders = extract_orders(objects)
        if not orders:
            messagebox.showwarning("No orders", "Could not find any orderNum in the pasted data.")
            return None
        return orders

    def send_sms(self):
        if self.busy:
            return
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("No token", "Enter and save a bearer token first.")
            return
        orders = self._prepare_orders()
        if orders is None:
            return
        template_id = self.template_var.get()

        self.busy = True
        self.events.put(("clear_post", None))
        self.status_var.set(f"Sending SMS to {len(orders)} order(s)...")
        threading.Thread(
            target=self._worker_sms, args=(orders, token, template_id), daemon=True
        ).start()

    def _worker_sms(self, orders, token, template_id):
        total = len(orders)
        for i, order in enumerate(orders, 1):
            payload = {
                "orderNum": order["orderNum"],
                "templateId": int(template_id),
                "country": order.get("country") or "NG",
                "appName": order.get("appName") or "",
            }
            resp, err = http_request("POST", SMS_URL, token, payload)
            if err:
                self.events.put(("append", f"FAILED SMS {order['orderNum']}: {err}\n"))
            elif resp and resp.get("code") == 200:
                self.events.put(("append", f"SMS SENT {order['orderNum']}\n"))
            else:
                msg = (resp or {}).get("msg") or "unknown error"
                self.events.put(("append", f"FAILED SMS {order['orderNum']}: {msg}\n"))
            self.events.put(("status", f"Sending SMS {i}/{total}..."))
        self.events.put(("status", f"SMS batch finished ({total} order(s))."))
        self.busy = False

    def add_report(self):
        if self.busy:
            return
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("No token", "Enter and save a bearer token first.")
            return
        orders = self._prepare_orders()
        if orders is None:
            return

        fields = {
            "reachOutBy": self.reach_out_by.get().strip() or "Phone",
            "contactRelations": self.contact_relations.get().strip() or "Self",
            "contactResult": self.contact_result.get().strip() or "No Reply",
            "collectionTag": self.collection_tag.get().strip(),
            "contactName": self.contact_name.get().strip(),
            "contactNo": self.contact_no.get().strip(),
            "remark": self.remark.get().strip(),
        }

        self.busy = True
        self.events.put(("clear_post", None))
        self.status_var.set(f"Adding report to {len(orders)} order(s)...")
        threading.Thread(
            target=self._worker_report, args=(orders, token, fields), daemon=True
        ).start()

    def _worker_report(self, orders, token, fields):
        total = len(orders)
        for i, order in enumerate(orders, 1):
            payload = {
                "orderNum": order["orderNum"],
                "reachOutBy": fields["reachOutBy"],
                "contactRelations": fields["contactRelations"],
                "contactResult": fields["contactResult"],
                "collectionTag": fields["collectionTag"],
                "contactName": fields["contactName"] or order.get("customerName") or "",
                "contactNo": fields["contactNo"] or order.get("phone") or "",
                "fraudVoucher": "",
                "promisedTime": "",
                "remark": fields["remark"],
            }
            resp, err = http_request("POST", REPORT_URL, token, payload)
            if err:
                self.events.put(("append", f"FAILED REPORT {order['orderNum']}: {err}\n"))
            elif resp and resp.get("code") == 200:
                self.events.put(("append", f"REPORT ADDED {order['orderNum']}\n"))
            else:
                msg = (resp or {}).get("msg") or "unknown error"
                self.events.put(("append", f"FAILED REPORT {order['orderNum']}: {msg}\n"))
            self.events.put(("status", f"Adding report {i}/{total}..."))
        self.events.put(("status", f"Report batch finished ({total} order(s))."))
        self.busy = False


def main():
    app = CollectionWorkbench()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        try:
            with open(sys.argv[1], "r", encoding="utf-8") as f:
                raw = f.read()
            app.get_input.insert("1.0", raw)
        except Exception:
            pass
    app.mainloop()


if __name__ == "__main__":
    main()