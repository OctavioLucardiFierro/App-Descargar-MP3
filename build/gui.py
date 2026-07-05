"""
Descargar MP3 de YouTube - tematica Miku Nakano.

Arreglos respecto de la version anterior:
- Se puede elegir la carpeta de destino y descarga con ruta absoluta
  (antes bajaba al directorio actual y fallaba fuera del escritorio).
- Genera un MP3 real con ffmpeg si esta disponible (antes solo renombraba).
- Ruta de assets relativa (funciona movido de carpeta y como .exe).
- Descarga en un hilo aparte con barra de progreso (la UI no se congela).
"""

import os
import sys
import shutil
import queue
import threading
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk, ImageDraw

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


# ----------------------------------------------------------------------------
# Paleta - color de Miku Nakano (azul, sus auriculares)
# ----------------------------------------------------------------------------
BG_TOP = "#141F3A"
BG_BOTTOM = "#243E68"
BLUE = "#4C86D6"
BLUE_HOVER = "#3A6BB0"
RING = "#5A86C8"
TROUGH = "#31456B"
INPUT_BG = "#EAF1FB"
INPUT_FG = "#12213B"
WHITE = "#FFFFFF"
MUTED = "#B9C6DD"
OK = "#8FE38C"
ERROR = "#E8657A"

W, H = 896, 560
CX = W // 2

PLACEHOLDER = "https://www.youtube.com/watch?v=..."


def resource_path(rel):
    """Ruta a recursos que funciona en dev y empaquetado con PyInstaller."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


ASSETS = resource_path(os.path.join("assets", "frame0"))


# ----------------------------------------------------------------------------
# Descarga
# ----------------------------------------------------------------------------
def descargar_mp3(link, outdir, hook):
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(outdir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "overwrites": True,
        "progress_hooks": [hook],
    }

    tiene_ffmpeg = shutil.which("ffmpeg") is not None
    if tiene_ffmpeg:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(link, download=True)
        base = ydl.prepare_filename(info)

    target = os.path.splitext(base)[0] + ".mp3"
    if tiene_ffmpeg:
        return target

    # Sin ffmpeg: renombramos el audio a .mp3 (reproduce, aunque no sea mp3 real).
    if os.path.abspath(base) != os.path.abspath(target):
        if os.path.exists(target):
            os.remove(target)
        os.rename(base, target)
    return target


# ----------------------------------------------------------------------------
# Dibujo
# ----------------------------------------------------------------------------
def round_rect(canvas, x1, y1, x2, y2, r=12, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def pick_font(root, prefs):
    fams = set(tkfont.families(root))
    for f in prefs:
        if f in fams:
            return f
    return prefs[-1]


def gradient_bg(w, h, top, bottom):
    def rgb(c):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    t, b = rgb(top), rgb(bottom)
    col = Image.new("RGB", (1, h))
    for y in range(h):
        f = y / max(1, h - 1)
        col.putpixel((0, y), tuple(int(t[i] + (b[i] - t[i]) * f) for i in range(3)))
    return col.resize((w, h))


def circular_avatar(path, size, ring_color, ring=9):
    im = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    im.putalpha(mask)

    total = size + ring * 2
    out = Image.new("RGBA", (total, total), (0, 0, 0, 0))
    dr = ImageDraw.Draw(out)
    r = tuple(int(ring_color[i:i + 2], 16) for i in (1, 3, 5))
    dr.ellipse((0, 0, total - 1, total - 1), fill=r + (255,))
    out.paste(im, (ring, ring), im)
    return out


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.q = queue.Queue()
        self.outdir = self._default_outdir()

        root.title("Descargar MP3 de Youtube")
        root.geometry(f"{W}x{H}")
        root.resizable(False, False)
        self._center()

        self.title_family = pick_font(root, ["Segoe UI Semibold", "Segoe UI", "Bahnschrift", "Arial"])
        self.body_family = pick_font(root, ["Segoe UI", "Arial"])

        # Avatares circulares (3 estados)
        self.avatars = {
            "normal": ImageTk.PhotoImage(circular_avatar(os.path.join(ASSETS, "NormalStateMikuIcon.png"), 244, RING)),
            "happy": ImageTk.PhotoImage(circular_avatar(os.path.join(ASSETS, "HappyMikuIcon.png"), 244, OK)),
            "surprised": ImageTk.PhotoImage(circular_avatar(os.path.join(ASSETS, "SuprisedMikuIcon.png"), 244, ERROR)),
        }
        try:
            self.icon = ImageTk.PhotoImage(Image.open(os.path.join(ASSETS, "NormalStateMikuIcon.png")))
            root.iconphoto(True, self.icon)
        except Exception:
            pass

        self.canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.bg = ImageTk.PhotoImage(gradient_bg(W, H, BG_TOP, BG_BOTTOM))
        self.canvas.create_image(0, 0, image=self.bg, anchor="nw")

        self._build_ui()
        self._build_menu()

    def _default_outdir(self):
        for name in ("Music", "Downloads"):
            p = os.path.join(os.path.expanduser("~"), name)
            if os.path.isdir(p):
                return p
        return os.path.expanduser("~")

    def _center(self):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")

    # -- UI ------------------------------------------------------------------
    def _build_ui(self):
        c = self.canvas

        c.create_text(CX, 46, text="Descargar MP3 de YouTube", fill=WHITE,
                      font=(self.title_family, 27, "bold"))
        c.create_text(CX, 82, text="Pega el link del video y baja el audio en MP3",
                      fill=MUTED, font=(self.body_family, 12))

        # Avatar Miku (columna izquierda) - refleja el estado
        self.avatar_item = c.create_image(200, 330, image=self.avatars["normal"])
        c.create_text(200, 476, text="Miku Nakano", fill=WHITE,
                      font=(self.title_family, 16, "bold"))
        c.create_text(200, 500, text="los auriculares primero", fill=MUTED,
                      font=(self.body_family, 10, "italic"))

        # Columna derecha (formulario)
        fx1, fx2 = 372, 852
        rcx = (fx1 + fx2) // 2

        c.create_text(fx1, 150, anchor="w", text="URL del video de YouTube",
                      fill=WHITE, font=(self.body_family, 12, "bold"))
        round_rect(c, fx1, 170, fx2, 214, r=18, fill=INPUT_BG, outline="")
        self.url = tk.StringVar()
        self.entry = tk.Entry(self.root, textvariable=self.url, bd=0, bg=INPUT_BG,
                              fg="#8a8a8a", font=(self.body_family, 12),
                              justify="center")
        self.entry.insert(0, PLACEHOLDER)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Return>", lambda e: self._on_download())
        c.create_window(rcx, 192, window=self.entry, width=440, height=32)

        # Carpeta destino
        self.dest_text = c.create_text(fx1, 246, anchor="w", fill=MUTED,
                                       font=(self.body_family, 10))
        link_id = c.create_text(fx2, 246, anchor="e", text="Cambiar carpeta",
                                fill="#7FB0E8", font=(self.body_family, 10, "underline"))
        c.tag_bind(link_id, "<Button-1>", lambda e: self._choose_dir())
        c.tag_bind(link_id, "<Enter>", lambda e: c.config(cursor="hand2"))
        c.tag_bind(link_id, "<Leave>", lambda e: c.config(cursor=""))
        self._refresh_dest()

        # Boton
        self.btn_rect = round_rect(c, rcx - 130, 285, rcx + 130, 341, r=14,
                                   fill=BLUE, outline="")
        self.btn_text = c.create_text(rcx, 313, text="Descargar MP3", fill=WHITE,
                                      font=(self.body_family, 14, "bold"))
        for item in (self.btn_rect, self.btn_text):
            c.tag_bind(item, "<Button-1>", lambda e: self._on_download())
            c.tag_bind(item, "<Enter>", self._btn_enter)
            c.tag_bind(item, "<Leave>", self._btn_leave)

        # Progreso
        self.status_text = c.create_text(fx1, 378, anchor="w", text="",
                                         fill=WHITE, font=(self.body_family, 11))
        self.pct_text = c.create_text(fx2, 378, anchor="e", text="",
                                      fill=WHITE, font=(self.body_family, 11))
        round_rect(c, fx1, 394, fx2, 414, r=10, fill=TROUGH, outline="")
        self.fill_id = None
        self.msg_text = c.create_text(rcx, 452, width=470, text="", fill=MUTED,
                                      justify="center", font=(self.body_family, 10))

        c.create_text(CX, 526, text="Hecho por Octavio  -  info del desarrollador en el menu",
                      fill=MUTED, font=(self.body_family, 9))

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        info = tk.Menu(menubar, tearoff=0)
        info.add_command(label="Informacion del desarrollador", command=self._open_dev)
        info.add_command(label="Abrir carpeta de descargas", command=self._open_folder)
        menubar.add_cascade(label="Mas informacion", menu=info)
        menubar.add_command(label="Salir", command=self.root.destroy)

    def _open_dev(self):
        webbrowser.open("https://www.linkedin.com/in/octavio-lucardi-fierro-4aba90251/")

    def _open_folder(self):
        try:
            os.startfile(self.outdir)
        except Exception:
            pass

    # -- Entry placeholder ---------------------------------------------------
    def _on_focus_in(self, _):
        if self.entry.get() == PLACEHOLDER:
            self.entry.delete(0, "end")
            self.entry.config(fg=INPUT_FG)

    def _on_focus_out(self, _):
        if not self.entry.get().strip():
            self.entry.delete(0, "end")
            self.entry.insert(0, PLACEHOLDER)
            self.entry.config(fg="#8a8a8a")

    def _get_link(self):
        v = self.entry.get().strip()
        return "" if v == PLACEHOLDER else v

    # -- Carpeta -------------------------------------------------------------
    def _choose_dir(self):
        if self.running:
            return
        chosen = filedialog.askdirectory(initialdir=self.outdir, title="Elegi la carpeta de descarga")
        if chosen:
            self.outdir = chosen
            self._refresh_dest()

    def _refresh_dest(self):
        p = self.outdir
        show = p if len(p) <= 52 else "..." + p[-49:]
        self.canvas.itemconfig(self.dest_text, text=f"Guardar en:  {show}")

    # -- Boton hover ---------------------------------------------------------
    def _btn_enter(self, _):
        if not self.running:
            self.canvas.itemconfig(self.btn_rect, fill=BLUE_HOVER)
            self.canvas.config(cursor="hand2")

    def _btn_leave(self, _):
        if not self.running:
            self.canvas.itemconfig(self.btn_rect, fill=BLUE)
            self.canvas.config(cursor="")

    # -- Estado / progreso ---------------------------------------------------
    def _avatar(self, name):
        self.canvas.itemconfig(self.avatar_item, image=self.avatars[name])

    def _set_progress(self, pct, color=BLUE):
        pct = max(0, min(100, pct))
        if self.fill_id is not None:
            self.canvas.delete(self.fill_id)
            self.fill_id = None
        if pct > 0:
            x1 = 372
            x2 = 372 + int((852 - 372) * pct / 100)
            self.fill_id = round_rect(self.canvas, x1, 394, x2, 414, r=10, fill=color, outline="")

    def _status(self, text, color=WHITE, pct=""):
        self.canvas.itemconfig(self.status_text, text=text, fill=color)
        self.canvas.itemconfig(self.pct_text, text=pct, fill=color)

    def _msg(self, text, color=MUTED):
        self.canvas.itemconfig(self.msg_text, text=text, fill=color)

    # -- Descarga ------------------------------------------------------------
    def _on_download(self):
        if self.running:
            return
        if yt_dlp is None:
            messagebox.showerror("Falta yt-dlp", "yt-dlp no esta instalado.\n\npip install yt-dlp")
            return
        link = self._get_link()
        if not link:
            self._status("Pega un link de YouTube", ERROR)
            self._avatar("surprised")
            return

        self.running = True
        self.canvas.itemconfig(self.btn_rect, fill="#5a6b86")
        self.canvas.itemconfig(self.btn_text, text="Descargando...")
        self._avatar("normal")
        self._msg("")
        self._set_progress(0)
        self._status("Iniciando...", WHITE)

        os.makedirs(self.outdir, exist_ok=True)
        threading.Thread(target=self._worker, args=(link, self.outdir), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, link, outdir):
        def hook(d):
            st = d.get("status")
            if st == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes", 0)
                self.q.put(("descargando", (done / total * 100) if total else 0))
            elif st == "finished":
                self.q.put(("procesando", 100))
        try:
            path = descargar_mp3(link, outdir, hook)
            self.q.put(("listo", path))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                self._handle(kind, val)
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._poll)

    def _handle(self, kind, val):
        if kind == "descargando":
            self._set_progress(val)
            self._status("Descargando audio...", WHITE, f"{round(val)}%")
        elif kind == "procesando":
            self._set_progress(100)
            self._status("Convirtiendo a MP3...", WHITE, "")
        elif kind == "listo":
            self._set_progress(100, OK)
            self._status("Listo", OK, "100%")
            self._msg(f"Guardado: {os.path.basename(val)}", OK)
            self._avatar("happy")
            self._finish()
            self._open_folder()
        elif kind == "error":
            self._set_progress(100, ERROR)
            self._status("Hubo un problema", ERROR, "")
            msg = val if len(val) <= 120 else val[:117] + "..."
            self._msg(msg, ERROR)
            self._avatar("surprised")
            self._finish()

    def _finish(self):
        self.running = False
        self.canvas.itemconfig(self.btn_rect, fill=BLUE)
        self.canvas.itemconfig(self.btn_text, text="Descargar MP3")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
