# -*- coding: utf-8 -*-
"""
Голосовой ввод через Groq Whisper large-v3.

Левый Ctrl + Пробел (или кнопка в окне) — старт записи, повторное нажатие — стоп.
Текст всегда попадает в буфер обмена, а если активно чужое окно — вставляется туда.
Последние 5 записей видны в окне, клик по записи копирует её заново.

Оформление — дизайн-система Pictotext «editorial terminal»
(D:\\Буткамп\\Pictotext SAAS\\app\\src\\styles\\tokens.css, решение владелицы D14):
один акцент-маркер, волосяные линии, нулевые скругления, моноширинный только для
данных, проза строчными.
"""

import ctypes
import io
import json
import math
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import keyboard
import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

# --- Токены Pictotext ---------------------------------------------------------
PAPER = "#fbfbf9"      # фон страницы
PANEL = "#ffffff"      # поверхность панели
STAGE = "#f1f1ea"      # «рабочая» половина
INK = "#14140f"        # основной текст
MUTED = "#5a5a50"      # вторичный текст
HAIRLINE = "#e3e3da"   # тонкая линия
EDGE = "#c3c3b7"       # рамка панели
ACCENT = "#ffdc2e"     # единственный акцент, только заливка
ACCENT_HOVER = "#ffe566"
ACCENT_INK = "#14140f"  # текст поверх акцента, контраст 13.8:1
ERROR = "#b54a34"

SANS = "Segoe UI"                    # проза и подписи контролов, строчными
MONO = "Cascadia Mono"               # только данные: время, счётчики, состояния
MONO_FALLBACK = "Consolas"
ICON_FAMILY = "Segoe Fluent Icons"   # системные глифы Windows 11
GLYPH_STOP = ""                # квадрат «стоп»

# --- Индикатор записи ---------------------------------------------------------
ICON_FONT_PATH = r"C:\Windows\Fonts\SegoeIcons.ttf"   # Segoe Fluent Icons
MIC_GLYPH = "\ue720"                                   # микрофон
ACCENT_RGB = (255, 220, 46)                            # ACCENT числами
ACCENT_INK_RGB = (20, 20, 15)

# --- Настройки ----------------------------------------------------------------
API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"
SAMPLE_RATE = 16000
HOTKEY = "left ctrl+space"
HISTORY_SIZE = 5
MIN_SECONDS = 0.3
MAX_SECONDS = 600

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Проводник кэширует иконки по пути файла и не перечитывает их при перезаписи,
# поэтому у обновлённого набора новое имя.
ICON_FILE = "groqer.ico"
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
# Ключ ищется по порядку: переменная окружения → groq.env рядом со скриптом →
# личное хранилище владельца. Первый существующий побеждает; записываем всегда
# в тот файл, который уже есть, иначе в соседний.
KEY_FILES = [os.path.join(APP_DIR, "groq.env"), r"D:\Dev\keys\groq.env"]

# Все языки, которые понимает whisper-large-v3. Пустой код = автоопределение.
LANGUAGE_NAMES = {
    "auto": "auto-detect", "af": "Afrikaans", "am": "Amharic", "ar": "Arabic",
    "as": "Assamese", "az": "Azerbaijani", "ba": "Bashkir", "be": "Belarusian",
    "bg": "Bulgarian", "bn": "Bengali", "bo": "Tibetan", "br": "Breton",
    "bs": "Bosnian", "ca": "Catalan", "cs": "Czech", "cy": "Welsh",
    "da": "Danish", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "et": "Estonian", "eu": "Basque", "fa": "Persian",
    "fi": "Finnish", "fo": "Faroese", "fr": "French", "gl": "Galician",
    "gu": "Gujarati", "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew",
    "hi": "Hindi", "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "is": "Icelandic", "it": "Italian",
    "ja": "Japanese", "jw": "Javanese", "ka": "Georgian", "kk": "Kazakh",
    "km": "Khmer", "kn": "Kannada", "ko": "Korean", "la": "Latin",
    "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao", "lt": "Lithuanian",
    "lv": "Latvian", "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian",
    "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay",
    "mt": "Maltese", "my": "Burmese", "ne": "Nepali", "nl": "Dutch",
    "nn": "Nynorsk", "no": "Norwegian", "oc": "Occitan", "pa": "Punjabi",
    "pl": "Polish", "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian",
    "ru": "Russian", "sa": "Sanskrit", "sd": "Sindhi", "si": "Sinhala",
    "sk": "Slovak", "sl": "Slovenian", "sn": "Shona", "so": "Somali",
    "sq": "Albanian", "sr": "Serbian", "su": "Sundanese", "sv": "Swedish",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "tg": "Tajik",
    "th": "Thai", "tk": "Turkmen", "tl": "Tagalog", "tr": "Turkish",
    "tt": "Tatar", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek",
    "vi": "Vietnamese", "yi": "Yiddish", "yo": "Yoruba", "yue": "Cantonese",
    "zh": "Chinese",
}
# Сверху то, чем пользуются каждый день, дальше — алфавит.
PINNED = ["auto", "ru", "en"]
LANGUAGE_ORDER = PINNED + sorted(
    (c for c in LANGUAGE_NAMES if c not in PINNED),
    key=lambda c: LANGUAGE_NAMES[c])


def language_label(code):
    return f"{LANGUAGE_NAMES.get(code, code)} ({code})" if code != "auto" \
        else LANGUAGE_NAMES["auto"]


def mono_family():
    """Cascadia Mono есть не на каждой машине — Consolas есть всегда."""
    try:
        from tkinter import font as tkfont
        return MONO if MONO in tkfont.families() else MONO_FALLBACK
    except Exception:
        return MONO_FALLBACK


APP_ID = "Groqer.VoiceTyping"


def set_app_id():
    """Своя запись в панели задач.

    Без явного AppUserModelID Windows считает окно частью группы pythonw.exe
    и берёт для панели иконку Python, сколько бы WM_SETICON мы ни слали.
    Вызывать до создания окна.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def enable_dpi_awareness():
    """Без этого Windows рисует окно в 96 dpi и растягивает картинкой —
    при масштабе дисплея 150% текст выходит мыльным. Вызывать до Tk()."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # system dpi aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def dpi_scale():
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def read_api_key():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    for path in KEY_FILES:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GROQ_API_KEY="):
                        value = line.split("=", 1)[1].strip()
                        return value.strip('"').strip("'")
        except Exception:
            continue
    return ""


def write_api_key(key):
    target = next((p for p in KEY_FILES if os.path.exists(p)), KEY_FILES[0])
    folder = os.path.dirname(target)
    if folder:
        os.makedirs(folder, exist_ok=True)
    lines = []
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines()
                     if not ln.startswith("GROQ_API_KEY=")]
    lines.append(f"GROQ_API_KEY={key}")
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def foreground_is_self():
    """True, если активно наше собственное окно — вставлять текст некуда."""
    try:
        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),
                                        ctypes.byref(pid))
        return pid.value == os.getpid()
    except Exception:
        return False


class Recorder:
    def __init__(self):
        self.frames = queue.Queue()
        self.stream = None
        self.started_at = 0.0

    def start(self):
        self.frames = queue.Queue()
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            callback=lambda data, *_: self.frames.put(data.copy()),
        )
        self.stream.start()
        self.started_at = time.time()

    def stop(self):
        if self.stream is None:
            return None, 0.0
        try:
            self.stream.stop()
            self.stream.close()
        finally:
            self.stream = None
        chunks = []
        while not self.frames.empty():
            chunks.append(self.frames.get())
        if not chunks:
            return None, 0.0
        audio = np.concatenate(chunks, axis=0)
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="FLAC")
        buf.seek(0)
        return buf, len(audio) / SAMPLE_RATE


def transcribe(audio, api_key, language):
    data = {"model": MODEL, "response_format": "json", "temperature": "0"}
    if language != "auto":
        data["language"] = language
    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": ("audio.flac", audio, "audio/flac")},
        data=data, timeout=120,
    )
    if r.status_code == 401:
        raise RuntimeError("key rejected")
    if r.status_code == 429:
        raise RuntimeError("rate limit, wait a minute")
    if r.status_code >= 400:
        raise RuntimeError(f"groq {r.status_code}")
    return (r.json().get("text") or "").strip()


# --- структуры Windows для индикатора ----------------------------------------
class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Size(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _Blend(ctypes.Structure):
    _fields_ = [("op", ctypes.c_byte), ("flags", ctypes.c_byte),
                ("alpha", ctypes.c_byte), ("fmt", ctypes.c_byte)]


class _BitmapHeader(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("width", ctypes.c_int32),
                ("height", ctypes.c_int32), ("planes", ctypes.c_uint16),
                ("bit_count", ctypes.c_uint16), ("compression", ctypes.c_uint32),
                ("size_image", ctypes.c_uint32), ("x_ppm", ctypes.c_int32),
                ("y_ppm", ctypes.c_int32), ("clr_used", ctypes.c_uint32),
                ("clr_important", ctypes.c_uint32)]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("header", _BitmapHeader), ("colors", ctypes.c_uint32 * 3)]


class Overlay(tk.Toplevel):
    """Маркер записи у курсора: жёлтый квадрат с чёрным микрофоном.

    Форма и цвет — те же, что у акцента в дизайн-системе: заливка-маркер,
    чернильный знак поверх, никаких скруглений. Рисуется через
    UpdateLayeredWindow — цветовой ключ дал бы рваный край. Окно висит
    неподвижно, не мигает, не забирает фокус и пропускает клики насквозь.
    """

    BASE_SIZE = 18       # логических пикселей макета
    PLATE_OPACITY = 0.3  # плашка — почти прозрачная
    MARK_OPACITY = 0.85  # знак — почти плотный, чтобы читался
    SUPERSAMPLE = 8
    OFFSET = (16, 20)    # сдвиг от кончика курсора вправо-вниз
    FOLLOW_MS = 40
    BREATH_MS = 3000     # полный вдох-выдох, неспешный
    BREATH_FLOOR = 0.42  # насколько гаснет на выдохе

    def __init__(self, master):
        super().__init__(master)
        # окно DPI-осознанное, поэтому размер и сдвиг считаем в физических
        scale = getattr(master, "scale", 1.0)
        self.SIZE = int(round(self.BASE_SIZE * scale))
        self.OFFSET = (int(round(16 * scale)), int(round(20 * scale)))
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.wm_attributes("-toolwindow", True)   # прячем из Alt+Tab
        except Exception:
            pass
        self.geometry(f"{self.SIZE}x{self.SIZE}+0+0")
        self.bits = None
        self.styled = False
        self.job = None
        self.phase = 0

    # --- картинка ------------------------------------------------------------
    def _draw_mic(self, draw, size):
        """Запасная отрисовка, если системный шрифт иконок недоступен."""
        cx, ink = size / 2, ACCENT_INK_RGB + (255,)
        draw.rounded_rectangle([cx - size * .09, size * .27, cx + size * .09,
                                size * .54], radius=size * .09, fill=ink)
        draw.arc([cx - size * .17, size * .34, cx + size * .17, size * .66],
                 0, 180, fill=ink, width=max(1, int(size * .045)))
        draw.line([cx, size * .64, cx, size * .74], fill=ink,
                  width=max(1, int(size * .045)))

    def _render(self):
        """Тот же рисунок, что у иконки приложения, но плашка почти прозрачная,
        а знак почти плотный — иначе микрофон выцветает вместе с фоном."""
        try:
            from make_icon import render
            return render(self.SIZE,
                          fill_alpha=int(255 * self.PLATE_OPACITY),
                          ink_alpha=int(255 * self.MARK_OPACITY)).convert("RGBA")
        except Exception:
            img = self._render_fallback()
            img.putalpha(img.getchannel("A").point(
                lambda v: int(v * self.MARK_OPACITY)))
            return img

    def _render_fallback(self):
        size = self.SIZE * self.SUPERSAMPLE
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size - 1, size - 1], fill=ACCENT_RGB + (255,),
                       outline=ACCENT_INK_RGB + (255,),
                       width=max(1, int(size * 0.045)))
        try:
            font = ImageFont.truetype(ICON_FONT_PATH, int(size * 0.66))
            draw.text((size / 2, size / 2), MIC_GLYPH, font=font,
                      fill=ACCENT_INK_RGB + (255,), anchor="mm")
        except Exception:
            self._draw_mic(draw, size)
        return img.resize((self.SIZE, self.SIZE), Image.LANCZOS)

    def _pixels(self):
        """BGRA с предумноженной альфой — в таком виде их ждёт Windows."""
        if self.bits is None:
            raw = bytearray(self._render().tobytes("raw", "BGRA"))
            for i in range(0, len(raw), 4):
                a = raw[i + 3]
                if a != 255:
                    raw[i] = raw[i] * a // 255
                    raw[i + 1] = raw[i + 1] * a // 255
                    raw[i + 2] = raw[i + 2] * a // 255
            self.bits = bytes(raw)
        return self.bits

    # --- окно ----------------------------------------------------------------
    def _hwnd(self):
        return ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()

    def _apply_styles(self):
        if self.styled:
            return
        user32, hwnd = ctypes.windll.user32, self._hwnd()
        GWL_EXSTYLE = -20
        LAYERED, TRANSPARENT, NOACTIVATE = 0x80000, 0x20, 0x8000000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | LAYERED | TRANSPARENT | NOACTIVATE)
        self.styled = True

    def _paint(self, x, y, alpha=255):
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        w = h = self.SIZE
        screen_dc = user32.GetDC(0)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        info = _BitmapInfo()
        info.header.size = ctypes.sizeof(_BitmapHeader)
        info.header.width, info.header.height = w, -h   # минус = сверху вниз
        info.header.planes, info.header.bit_count = 1, 32
        info.header.compression = 0
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(mem_dc, ctypes.byref(info), 0,
                                        ctypes.byref(bits), None, 0)
        raw = self._pixels()
        ctypes.memmove(bits, raw, len(raw))
        old = gdi32.SelectObject(mem_dc, bitmap)
        blend = _Blend(0, 0, alpha, 1)                  # AC_SRC_OVER + альфа
        user32.UpdateLayeredWindow(self._hwnd(), screen_dc,
                                   ctypes.byref(_Point(x, y)),
                                   ctypes.byref(_Size(w, h)), mem_dc,
                                   ctypes.byref(_Point(0, 0)), 0,
                                   ctypes.byref(blend), 2)   # ULW_ALPHA
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)

    def _cursor_spot(self):
        """Точка рядом с курсором, не вылезающая за край экрана."""
        pt = _Point()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        x = min(max(pt.x + self.OFFSET[0], 0),
                self.winfo_screenwidth() - self.SIZE)
        y = min(max(pt.y + self.OFFSET[1], 0),
                self.winfo_screenheight() - self.SIZE)
        return x, y

    def _follow(self):
        """Догоняем курсор и ведём дыхание одной перерисовкой: косинус даёт
        плавную волну без рывков на разворотах, а UpdateLayeredWindow за тот
        же вызов задаёт и позицию, и общую прозрачность."""
        self.phase = (self.phase + self.FOLLOW_MS) % self.BREATH_MS
        wave = 0.5 + 0.5 * math.cos(2 * math.pi * self.phase / self.BREATH_MS)
        alpha = int(255 * (self.BREATH_FLOOR + (1 - self.BREATH_FLOOR) * wave))
        x, y = self._cursor_spot()
        self._paint(x, y, alpha)
        self.job = self.after(self.FOLLOW_MS, self._follow)

    def show(self):
        self.deiconify()
        self.update_idletasks()
        self._apply_styles()
        self.phase = 0
        self._paint(*self._cursor_spot())
        self.attributes("-topmost", True)
        self._follow()

    def hide(self):
        if self.job:
            self.after_cancel(self.job)
            self.job = None
        self.withdraw()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.api_key = read_api_key()
        self.recorder = Recorder()
        self.recording = False
        self.busy = False
        self.history = []
        self.tick_job = None
        self.mono = mono_family()
        self.scale = dpi_scale()
        # Тк рисует в физических пикселях, поэтому пункты шрифта пересчитываем
        # сами: 1 пункт = 1/72 дюйма, дюйм = 96·scale пикселей.
        self.tk.call("tk", "scaling", self.scale * 96 / 72)

        self.title("Groqer")
        self._apply_icon()
        self.configure(bg=PAPER)
        self.geometry(f"{self.S(420)}x{self.S(520)}")
        self.minsize(self.S(380), self.S(440))
        self._build()
        self.overlay = Overlay(self)
        self._bind_hotkey()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_icon(self):
        """Иконку ставим через WM_SETICON, а не iconbitmap.

        Tk берёт из .ico одну запись и растягивает её под нужный размер сам —
        в заголовке окна знак получается мыльным. LoadImage с явными cx/cy
        выбирает из файла подходящую отрисовку, поэтому в титуле оказывается
        ровно тот вариант, что нарисован под этот размер.
        """
        path = os.path.join(APP_DIR, ICON_FILE)
        if not os.path.exists(path):
            return
        try:
            self.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
            IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
            WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
            SM_CXICON, SM_CXSMICON = 11, 49
            self._icon_handles = []
            for which, metric in ((ICON_SMALL, SM_CXSMICON), (ICON_BIG, SM_CXICON)):
                side = user32.GetSystemMetrics(metric) or 16
                handle = user32.LoadImageW(None, path, IMAGE_ICON, side, side,
                                           LR_LOADFROMFILE)
                if handle:
                    user32.SendMessageW(hwnd, WM_SETICON, which, handle)
                    self._icon_handles.append(handle)   # держим, чтобы не пропали
        except Exception:
            try:
                self.iconbitmap(path)
            except Exception:
                pass

    # --- разметка ------------------------------------------------------------
    def S(self, n):
        """Логические пиксели макета → физические пиксели экрана."""
        return int(round(n * self.scale))

    def _rule(self, parent, pad=(0, 0)):
        tk.Frame(parent, bg=HAIRLINE, height=max(1, self.S(1))).pack(
            fill="x", pady=(self.S(pad[0]), self.S(pad[1])))

    def _build(self):
        root = tk.Frame(self, bg=PAPER, padx=self.S(22), pady=self.S(20))
        root.pack(fill="both", expand=True)

        # шапка: имя строчными + состояние в фигурных скобках моноширинным
        head = tk.Frame(root, bg=PAPER)
        head.pack(fill="x")
        title = tk.Frame(head, bg=PAPER)
        title.pack(side="left")
        tk.Label(title, text="Groqer", bg=PAPER, fg=INK,
                 font=(SANS, 20), anchor="w").pack(anchor="w")
        tk.Label(title, text="speech → text", bg=PAPER, fg=MUTED,
                 font=(SANS, 9), anchor="w").pack(anchor="w")
        self.status = tk.Label(head, text="{ready}", bg=PAPER, fg=MUTED,
                               font=(self.mono, 9), anchor="e")
        self.status.pack(side="right", pady=(self.S(8), 0))

        self._rule(root, (14, 0))

        # кнопка записи: акцент-заливка, чернильная рамка, знак и подпись
        # набраны по правилу системы — глиф из системного набора, слово прозой
        stage = tk.Frame(root, bg=STAGE, padx=self.S(16), pady=self.S(16))
        stage.pack(fill="x")
        self.button = tk.Frame(stage, bg=ACCENT, cursor="hand2",
                               highlightthickness=self.S(2),
                               highlightbackground=INK, highlightcolor=INK)
        self.button.pack(fill="x")
        inner = tk.Frame(self.button, bg=ACCENT, pady=self.S(11))
        inner.pack()
        self.btn_icon = tk.Label(inner, text=MIC_GLYPH, bg=ACCENT,
                                 fg=ACCENT_INK, font=(ICON_FAMILY, 12))
        self.btn_icon.pack(side="left", padx=(0, self.S(9)))
        self.btn_text = tk.Label(inner, text="Speak", bg=ACCENT, fg=ACCENT_INK,
                                 font=(SANS, 11, "bold"))
        self.btn_text.pack(side="left")
        self.button_parts = (self.button, inner, self.btn_icon, self.btn_text)
        for w in self.button_parts:
            w.bind("<Button-1>", lambda _e: self.toggle())
            w.bind("<Enter>", lambda _e: self._hover_button(True))
            w.bind("<Leave>", lambda _e: self._hover_button(False))
        tk.Label(stage, text="Ctrl+Space", bg=STAGE, fg=MUTED,
                 font=(self.mono, 8), anchor="w").pack(fill="x",
                                                       pady=(self.S(9), 0))

        self._rule(root, (16, 0))

        tk.Label(root, text="recent", bg=PAPER, fg=MUTED,
                 font=(SANS, 9), anchor="w").pack(fill="x", pady=(self.S(12), 0))
        self.hist_frame = tk.Frame(root, bg=PAPER)
        self.hist_frame.pack(fill="both", expand=True, pady=(self.S(8), 0))
        self._render_history()

        foot = tk.Frame(root, bg=PAPER)
        foot.pack(fill="x", side="bottom", pady=(self.S(12), 0))
        self.lang = self.cfg.get("language", "ru")
        if self.lang not in LANGUAGE_NAMES:
            self.lang = "auto"
        self._init_combo_style()
        self.lang_var = tk.StringVar(value=language_label(self.lang))
        self.lang_box = ttk.Combobox(
            foot, textvariable=self.lang_var, state="readonly", width=19,
            values=[language_label(c) for c in LANGUAGE_ORDER],
            font=(self.mono, 8), style="Groqer.TCombobox")
        self.lang_box.pack(side="left")
        self.lang_box.bind("<<ComboboxSelected>>", self._on_language)
        self.hint = tk.Label(foot, text="", bg=PAPER, fg=MUTED,
                             font=(self.mono, 8))
        self.hint.pack(side="right")

        self.key_frame = tk.Frame(root, bg=PAPER)
        if not self.api_key:
            self._build_key_form()

    def _build_key_form(self):
        self.key_frame.pack(fill="x", side="bottom", pady=(12, 0))
        tk.Label(self.key_frame, text="groq key", bg=PAPER, fg=MUTED,
                 font=(self.mono, 8), anchor="w").pack(fill="x", pady=(0, 5))
        row = tk.Frame(self.key_frame, bg=PAPER)
        row.pack(fill="x")
        self.key_entry = tk.Entry(row, show="•", bg=PANEL, fg=INK,
                                  font=(self.mono, 9), relief="flat",
                                  insertbackground=INK, highlightthickness=1,
                                  highlightbackground=EDGE, highlightcolor=INK)
        self.key_entry.pack(side="left", fill="x", expand=True, ipady=6)
        save = tk.Label(row, text="ok", bg=ACCENT, fg=ACCENT_INK,
                        font=(self.mono, 9, "bold"), cursor="hand2", padx=16,
                        highlightthickness=2, highlightbackground=INK)
        save.pack(side="left", padx=(8, 0), ipady=5)
        save.bind("<Button-1>", lambda _e: self._save_key())

    def _save_key(self):
        key = self.key_entry.get().strip()
        if not key:
            return
        try:
            write_api_key(key)
        except Exception as e:
            self._set_status(f"key not saved: {e}", error=True)
            return
        self.api_key = key
        self.key_frame.pack_forget()
        self._set_status("ready")

    # --- состояния -----------------------------------------------------------
    def _render_button(self, hover=False):
        """Покой — маркер; запись — та же рамка, но выцветшая заливка,
        чтобы состояние читалось формой, а не вторым цветом."""
        if self.recording:
            bg = STAGE if hover else PANEL
            fg, text, glyph = INK, "Stop", GLYPH_STOP
        else:
            bg = ACCENT_HOVER if hover else ACCENT
            fg, text, glyph = ACCENT_INK, "Speak", MIC_GLYPH
        for w in self.button_parts:
            w.config(bg=bg)
        self.btn_icon.config(fg=fg, text=glyph)
        self.btn_text.config(fg=fg, text=text)

    def _hover_button(self, on):
        self._render_button(hover=on)

    def _init_combo_style(self):
        """Combobox под систему: плоский, волосяная рамка, выбор — маркером."""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Groqer.TCombobox", fieldbackground=PAPER,
                        background=PAPER, foreground=INK, bordercolor=HAIRLINE,
                        lightcolor=HAIRLINE, darkcolor=HAIRLINE,
                        arrowcolor=MUTED, arrowsize=self.S(11),
                        padding=self.S(3), relief="flat")
        style.map("Groqer.TCombobox",
                  fieldbackground=[("readonly", PAPER)],
                  bordercolor=[("focus", EDGE), ("hover", EDGE)],
                  selectbackground=[("readonly", PAPER)],
                  selectforeground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", ACCENT_INK)
        self.option_add("*TCombobox*Listbox.font", f"{{{self.mono}}} 8")

    def _on_language(self, _=None):
        label = self.lang_var.get()
        for code in LANGUAGE_ORDER:
            if language_label(code) == label:
                self.lang = code
                break
        self.cfg["language"] = self.lang
        save_config(self.cfg)
        self.focus_set()          # снимаем подсветку выделения с поля

    def _set_status(self, text, error=False):
        self.status.config(text="{" + text + "}", fg=ERROR if error else MUTED)

    # --- горячая клавиша -----------------------------------------------------
    def _bind_hotkey(self):
        try:
            keyboard.add_hotkey(HOTKEY, lambda: self.after(0, self.toggle),
                                suppress=True)
        except Exception as e:
            self.after(100, lambda: self._set_status(f"hotkey busy: {e}",
                                                     error=True))

    # --- запись --------------------------------------------------------------
    def toggle(self):
        if self.busy:
            return
        self._stop() if self.recording else self._start()

    def _start(self):
        if not self.api_key:
            self._set_status("no groq key", error=True)
            return
        try:
            self.recorder.start()
        except Exception as e:
            self._set_status(f"no mic: {e}", error=True)
            return
        self.recording = True
        self._render_button()
        self.overlay.show()
        self._tick()

    def _tick(self):
        if not self.recording:
            return
        sec = int(time.time() - self.recorder.started_at)
        if sec >= MAX_SECONDS:
            self._stop()
            return
        self._set_status(f"recording {sec // 60}:{sec % 60:02d}")
        self.tick_job = self.after(500, self._tick)

    def _stop(self):
        self.recording = False
        self.overlay.hide()
        self._render_button()
        if self.tick_job:
            self.after_cancel(self.tick_job)
            self.tick_job = None
        audio, seconds = self.recorder.stop()
        if audio is None or seconds < MIN_SECONDS:
            self._set_status("ready")
            return
        self.busy = True
        self._set_status("transcribing")
        threading.Thread(target=self._work, args=(audio,), daemon=True).start()

    def _work(self, audio):
        try:
            text = transcribe(audio, self.api_key, self.lang)
            self.after(0, self._done, text)
        except Exception as e:
            self.after(0, lambda: self._fail(str(e)))

    def _done(self, text):
        self.busy = False
        if not text:
            self._set_status("no speech")
            return
        self._copy(text)
        if foreground_is_self():
            self._set_status("copied")
        else:
            keyboard.send("ctrl+v")
            self._set_status("pasted")
        self._add_history(text)

    def _fail(self, message):
        self.busy = False
        self._set_status(message, error=True)

    # --- история -------------------------------------------------------------
    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def _add_history(self, text):
        self.history.insert(0, (datetime.now().strftime("%H:%M"), text))
        del self.history[HISTORY_SIZE:]
        self._render_history()

    def _render_history(self):
        for w in self.hist_frame.winfo_children():
            w.destroy()
        if not self.history:
            tk.Label(self.hist_frame, text="—", bg=PAPER, fg=MUTED,
                     font=(self.mono, 9), anchor="w").pack(fill="x")
            return
        for index, (stamp, text) in enumerate(self.history):
            if index:
                tk.Frame(self.hist_frame, bg=HAIRLINE, height=1).pack(fill="x")
            row = tk.Frame(self.hist_frame, bg=PAPER, cursor="hand2", pady=8)
            row.pack(fill="x")
            time_lbl = tk.Label(row, text=stamp, bg=PAPER, fg=MUTED,
                                font=(self.mono, 8), anchor="nw", width=6)
            time_lbl.pack(side="left", anchor="n")
            body = tk.Label(row, text=text, bg=PAPER, fg=INK, font=(SANS, 10),
                            anchor="w", justify="left",
                            wraplength=self.S(300))
            body.pack(side="left", fill="x", expand=True)
            for w in (row, time_lbl, body):
                w.bind("<Button-1>", lambda _e, t=text: self._copy_again(t))
                w.bind("<Enter>", lambda _e, r=row, b=body, t=time_lbl:
                       [x.config(bg=STAGE) for x in (r, b, t)])
                w.bind("<Leave>", lambda _e, r=row, b=body, t=time_lbl:
                       [x.config(bg=PAPER) for x in (r, b, t)])

    def _copy_again(self, text):
        self._copy(text)
        self.hint.config(text="copied")
        self.after(1500, lambda: self.hint.config(text=""))

    def _on_close(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        if self.recording:
            self.recorder.stop()
        self.destroy()


if __name__ == "__main__":
    set_app_id()
    enable_dpi_awareness()
    App().mainloop()
