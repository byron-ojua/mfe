import os
import json
from datetime import datetime
from collections import defaultdict
from threading import Thread

import tkinter as tk
from tkinter import filedialog, messagebox

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PIL import Image

CONFIG_FILE = "config.json"


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"input_dir": "", "output_dir": "", "archive_dir": "", "auto_start": True}


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


class EyeHandler(FileSystemEventHandler):
    def __init__(self, output_dir, archive_dir):
        super().__init__()
        self.pending = defaultdict(dict)
        self.output_dir = output_dir
        self.archive_dir = archive_dir

    def on_created(self, event):
        if event.is_directory or not event.src_path.lower().endswith(('.jpg', '.jpeg', '.png')):
            return
        self._process_file(event.src_path)

    def _process_file(self, path):
        fn = os.path.basename(path)
        tokens = os.path.splitext(fn)[0].split('_')
        if len(tokens) < 5 or tokens[3] not in ('R','L'):
            return
        eye = tokens[3]
        key = '_'.join(tokens[:3] + tokens[4:])
        date = datetime.strptime(tokens[1], '%Y%m%d')
        year, month, day = date.year, date.strftime('%m'), date.strftime('%d')
        self.pending[key][eye] = path
        if 'L' in self.pending[key] and 'R' in self.pending[key]:
            self.create_pdf(key, year, month, day)

    def create_pdf(self, key, year, month, day):
        paths = [self.pending[key][e] for e in ('L','R')]
        out_pdf = os.path.join(self.output_dir, f"{key}.pdf")
        imgs = [Image.open(p).convert('RGB') for p in paths]
        imgs[0].save(out_pdf, save_all=True, append_images=imgs[1:])
        archive_path = os.path.join(self.archive_dir, str(year), month, day)
        os.makedirs(archive_path, exist_ok=True)
        for p in paths:
            os.rename(p, os.path.join(archive_path, os.path.basename(p)))
        del self.pending[key]


class App:
    def __init__(self, master):
        self.master = master
        master.title("Eye PDF Watcher")

        # Load saved paths and settings
        cfg = load_config()
        self.input_dir   = tk.StringVar(value=cfg.get("input_dir", ""))
        self.output_dir  = tk.StringVar(value=cfg.get("output_dir", ""))
        self.archive_dir = tk.StringVar(value=cfg.get("archive_dir", ""))
        self.auto_start  = tk.BooleanVar(value=cfg.get("auto_start", True))

        # Directory selectors
        for i,(label,var) in enumerate([
            ("Input Folder:",    self.input_dir),
            ("PDF Output:",      self.output_dir),
            ("Archive Folder:",  self.archive_dir),
        ]):
            tk.Label(master, text=label).grid(row=i, column=0, sticky='e')
            entry = tk.Entry(master, textvariable=var, width=40)
            entry.grid(row=i, column=1, padx=5)
            btn = tk.Button(master, text="Browse", command=lambda v=var: self.browse(v))
            btn.grid(row=i, column=2)
            setattr(self, f"entry_{i}", entry)
            setattr(self, f"btn_{i}", btn)

        # Auto-start checkbutton
        self.auto_chk = tk.Checkbutton(master, text="Auto Start", variable=self.auto_start, command=self.save_settings)
        self.auto_chk.grid(row=3, column=0, columnspan=2, sticky='w', padx=5)

        # Start / Stop / Backfill buttons
        self.start_btn    = tk.Button(master, text="Start Watching", command=self.start_watching)
        self.start_btn.grid(row=4, column=0, pady=10)
        self.stop_btn     = tk.Button(master, text="Stop Watching",  command=self.stop_watching, state='disabled')
        self.stop_btn.grid(row=4, column=1)
        self.backfill_btn = tk.Button(master, text="Backfill", command=self.backfill)
        self.backfill_btn.grid(row=4, column=2)

        self.status = tk.Label(master, text="Idle", fg="blue")
        self.status.grid(row=5, column=0, columnspan=3)

        self.observer = None

        # Auto-start if enabled and dirs set
        if self.auto_start.get() and all([self.input_dir.get(), self.output_dir.get(), self.archive_dir.get()]):
            self.start_watching()

    def save_settings(self):
        save_config({
            "input_dir":   self.input_dir.get(),
            "output_dir":  self.output_dir.get(),
            "archive_dir": self.archive_dir.get(),
            "auto_start":  self.auto_start.get(),
        })

    def browse(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)
            self.save_settings()

    def set_controls_state(self, editing):
        state_entry = 'normal' if editing else 'disabled'
        state_btn   = 'normal' if editing else 'disabled'
        for i in range(3):
            getattr(self, f"entry_{i}").config(state=state_entry)
            getattr(self, f"btn_{i}").config(state=state_btn)
        self.start_btn.config(state='normal' if editing else 'disabled')
        self.stop_btn.config(state='disabled' if editing else 'normal')
        self.backfill_btn.config(state='normal')
        self.auto_chk.config(state=state_entry)

    def start_watching(self):
        if not all([self.input_dir.get(), self.output_dir.get(), self.archive_dir.get()]):
            messagebox.showwarning("Missing Paths", "Please set all three directories.")
            return
        self.save_settings()
        self.set_controls_state(editing=False)
        handler = EyeHandler(self.output_dir.get(), self.archive_dir.get())
        self.observer = Observer()
        self.observer.schedule(handler, self.input_dir.get(), recursive=False)
        Thread(target=self.observer.start, daemon=True).start()
        self.status.config(text="Watching…", fg="green")

    def stop_watching(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.set_controls_state(editing=True)
        self.status.config(text="Stopped", fg="red")

    def backfill(self):
        input_dir = self.input_dir.get()
        if not input_dir:
            messagebox.showwarning("Missing Input Folder", "Set the input folder first.")
            return
        handler = EyeHandler(self.output_dir.get(), self.archive_dir.get())
        pending = defaultdict(dict)
        for fname in os.listdir(input_dir):
            path = os.path.join(input_dir, fname)
            if os.path.isdir(path) or not fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            tokens = os.path.splitext(fname)[0].split('_')
            if len(tokens) < 5 or tokens[3] not in ('R','L'):
                continue
            eye = tokens[3]
            key = '_'.join(tokens[:3] + tokens[4:])
            date = datetime.strptime(tokens[1], '%Y%m%d')
            pending[key][eye] = (path, date)
        count = 0
        for key, eyes in pending.items():
            if 'L' in eyes and 'R' in eyes:
                pathL, date = eyes['L']
                pathR, _    = eyes['R']
                handler.pending[key] = {'L': pathL, 'R': pathR}
                handler.create_pdf(key, date.year, date.strftime('%m'), date.strftime('%d'))
                count += 1
        messagebox.showinfo("Backfill Complete", f"Processed {count} pairs.")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()