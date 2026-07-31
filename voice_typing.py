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
DEFAULT_HOTKEY = "left ctrl+space"
MODIFIERS = ("ctrl", "alt", "shift", "windows")


def pretty_hotkey(combo):
    """ctrl+space → Ctrl+Space. Левый и правый модификаторы показываем просто."""
    names = {"ctrl": "Ctrl", "left ctrl": "Ctrl", "right ctrl": "Ctrl",
             "alt": "Alt", "left alt": "Alt", "right alt": "Alt",
             "shift": "Shift", "left shift": "Shift", "right shift": "Shift",
             "windows": "Win", "space": "Space", "enter": "Enter",
             "esc": "Esc", "tab": "Tab", "backspace": "Backspace"}
    parts = [p.strip() for p in combo.split("+")]
    return "+".join(names.get(p, p.upper() if len(p) == 1 else p.capitalize())
                    for p in parts)
HISTORY_SIZE = 5
# Речь даёт примерно 950 знаков в минуту (140 слов на 7 знаков со пробелом).
# Дольше минуты — текст уже не помещается в окно целиком, поэтому уходит файлом.
LONG_TEXT_CHARS = 900
# В списке показываем начало: 160 знаков — это три строки, и пять записей
# помещаются в окно, не выдавливая друг друга.
PREVIEW_CHARS = 160
MIN_SECONDS = 0.3
# Предохранитель: на бесплатном тарифе Groq суточная норма — 8 часов аудио,
# поэтому одна запись не должна съедать её целиком.
MAX_SECONDS = 7 * 3600
# Сколько ждать распознавание при выходе (шаг 0,5 с) — десять минут с запасом
# хватает даже длинной записи, дальше выходим, чтобы не держать пользователя.
QUIT_MAX_WAITS = 1200
# Groq принимает файл до 25 МБ — это около 40 минут нашего FLAC, поэтому режем
# с запасом по получасу и склеиваем расшифровки.
CHUNK_SECONDS = 1800
# Насколько далеко от расчётной границы искать паузу, чтобы не резать по слову.
CHUNK_SEARCH_SECONDS = 12
# Потолок Groq — 25 МБ на запрос. Держим запас: сжатие FLAC зависит от голоса и
# шума, и на плотной начитке кусок может оказаться крупнее расчётного.
MAX_UPLOAD_BYTES = 23 * 1024 * 1024
# Паузы между повторами при временных сбоях сети и лимитов.
RETRY_DELAYS = [3, 12, 30]

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(APP_DIR, "transcripts")
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


# Это же имя Windows подставляет как заголовок всплывающих уведомлений,
# поэтому оно короткое, без технического суффикса.
APP_ID = "Groqer"


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


def foreground_window():
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


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
        # у семичасовой записи копия весит под гигабайт: держать обе разом
        # незачем, а момент остановки — самое неудачное место для нехватки памяти
        chunks.clear()
        return audio, len(audio) / SAMPLE_RATE


def save_transcript(text):
    """Длинную расшифровку кладём файлом рядом с приложением: в окно такой
    текст не помещается, а терять его нельзя. Возвращает путь или None."""
    try:
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".txt"
        path = os.path.join(TRANSCRIPTS_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path
    except Exception:
        return None


def append_partial(path, text):
    """Дописываем каждый расшифрованный кусок сразу на диск: если дальше
    оборвётся сеть, сделанное уже не пропадёт вместе с процессом."""
    try:
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        if path is None:
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = os.path.join(TRANSCRIPTS_DIR, stamp + ".txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(text.strip() + " ")
        return path
    except Exception:
        return path


def save_audio(audio):
    """Сырое аудио на диск — последняя линия обороны, когда расшифровать
    не удалось или пользователь выходит прямо во время записи."""
    try:
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(TRANSCRIPTS_DIR, stamp + ".flac")
        sf.write(path, audio, SAMPLE_RATE, format="FLAC")
        return path
    except Exception:
        return None


def encode_flac(audio):
    """FLAC в памяти: без потерь и примерно 10 КБ на секунду речи."""
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="FLAC")
    buf.seek(0)
    return buf


def split_audio(audio):
    """Режет длинную запись на куски не длиннее CHUNK_SECONDS.

    Граница сдвигается к самому тихому месту в окне вокруг расчётной точки,
    иначе разрез пришёлся бы на середину слова и оба куска потеряли бы его.
    """
    chunk = CHUNK_SECONDS * SAMPLE_RATE
    if len(audio) <= chunk:
        return [audio]

    search = CHUNK_SEARCH_SECONDS * SAMPLE_RATE
    window = SAMPLE_RATE // 10                      # шаг поиска — 100 мс
    cuts, pos = [], chunk
    while pos < len(audio):
        lo, hi = max(0, pos - search), min(len(audio), pos + search)
        quietest, best = None, pos
        for start in range(lo, hi - window, window):
            level = np.abs(audio[start:start + window]).mean()
            if quietest is None or level < quietest:
                quietest, best = level, start + window // 2
        cuts.append(best)
        pos = best + chunk

    parts, prev = [], 0
    for cut in cuts + [len(audio)]:
        if cut > prev:
            parts.append(audio[prev:cut])
        prev = cut
    return parts


class Transient(RuntimeError):
    """Сбой, который имеет смысл повторить: сеть, таймаут, 429, 5xx."""


def transcribe(audio, api_key, language):
    data = {"model": MODEL, "response_format": "json", "temperature": "0"}
    if language != "auto":
        data["language"] = language
    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("audio.flac", audio, "audio/flac")},
            data=data, timeout=180,
        )
    except requests.RequestException as e:
        raise Transient(f"network: {type(e).__name__}")
    if r.status_code == 401:
        raise RuntimeError("key rejected")
    if r.status_code == 413:
        raise RuntimeError("chunk too large")
    if r.status_code == 429 or r.status_code >= 500:
        raise Transient(f"groq {r.status_code}")
    if r.status_code >= 400:
        raise RuntimeError(f"groq {r.status_code}")
    return (r.json().get("text") or "").strip()


def transcribe_retrying(audio, api_key, language, on_wait=None):
    """Повторяем временные сбои: один моргнувший wi-fi не должен стоить
    пользователю всей записи."""
    delay = RETRY_DELAYS[0]
    for attempt, delay in enumerate(RETRY_DELAYS + [None], 1):
        try:
            audio.seek(0)
            return transcribe(audio, api_key, language)
        except Transient as e:
            if delay is None:
                raise RuntimeError(f"{e} — gave up after {attempt} tries")
            if on_wait:
                on_wait(str(e), delay)
            time.sleep(delay)


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
        """Точка рядом с курсором, прижатая к границам всего рабочего стола.

        Считаем по виртуальному экрану, а не по главному монитору: иначе на
        втором мониторе маркер улетал бы к краю первого.
        """
        user32 = ctypes.windll.user32
        pt = _Point()
        user32.GetCursorPos(ctypes.byref(pt))
        SM_XVIRTUAL, SM_YVIRTUAL, SM_CXVIRTUAL, SM_CYVIRTUAL = 76, 77, 78, 79
        left = user32.GetSystemMetrics(SM_XVIRTUAL)
        top = user32.GetSystemMetrics(SM_YVIRTUAL)
        width = user32.GetSystemMetrics(SM_CXVIRTUAL) or self.winfo_screenwidth()
        height = user32.GetSystemMetrics(SM_CYVIRTUAL) or self.winfo_screenheight()
        x = min(max(pt.x + self.OFFSET[0], left), left + width - self.SIZE)
        y = min(max(pt.y + self.OFFSET[1], top), top + height - self.SIZE)
        return x, y

    def _follow(self):
        """Догоняем курсор и ведём дыхание одной перерисовкой: косинус даёт
        плавную волну без рывков на разворотах, а UpdateLayeredWindow за тот
        же вызов задаёт и позицию, и общую прозрачность."""
        # Страховка от рассинхрона: индикатор существует только пока идёт
        # запись, что бы ни случилось с состоянием выше.
        if not getattr(self.master, "recording", False):
            self.hide()
            return
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
        self.capturing = False
        self.shutting_down = False
        self.quit_waits = 0
        self.target_window = None
        self.hotkey_handle = None
        self.hotkey = self.cfg.get("hotkey", DEFAULT_HOTKEY)
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
        self.hinted_tray = False
        self.tray = self._build_tray()
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
        # строка хоткея — кликом переводится в режим записи новой комбинации
        self.hotkey_label = tk.Label(stage, bg=STAGE, fg=MUTED,
                                     font=(self.mono, 8), anchor="w",
                                     cursor="hand2", padx=self.S(4),
                                     pady=self.S(2))
        self.hotkey_label.pack(fill="x", pady=(self.S(9), 0))
        self.hotkey_label.bind("<Button-1>", self._capture_hotkey)
        self.hotkey_label.bind("<Enter>", lambda _e: self.capturing or
                               self.hotkey_label.config(fg=INK))
        self.hotkey_label.bind("<Leave>", lambda _e: self.capturing or
                               self.hotkey_label.config(fg=MUTED))
        self._render_hotkey()

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
            self.hotkey_handle = keyboard.add_hotkey(
                self.hotkey, lambda: self.after(0, self.toggle), suppress=True)
        except Exception as e:
            self.hotkey_handle = None
            self.after(100, lambda: self._set_status(f"hotkey busy: {e}",
                                                     error=True))

    def _render_hotkey(self):
        self.hotkey_label.config(text=f"{pretty_hotkey(self.hotkey)}   ·  click to change",
                                 bg=STAGE, fg=MUTED)

    def _capture_hotkey(self, _=None):
        """Как в привычных приложениях: строка становится приёмником — нажатая
        комбинация и станет новым хоткеем."""
        if self.capturing or self.recording:
            return
        self.capturing = True
        self.hotkey_label.config(text="press keys…", bg=ACCENT, fg=ACCENT_INK)
        try:
            if self.hotkey_handle:
                keyboard.remove_hotkey(self.hotkey_handle)
        except Exception:
            pass
        threading.Thread(target=self._capture_worker, daemon=True).start()

    def _capture_worker(self):
        try:
            combo = keyboard.read_hotkey(suppress=False)
        except Exception:
            combo = None
        self.after(0, self._finish_capture, combo)

    def _finish_capture(self, combo):
        # без модификатора хоткей отбирал бы обычную клавишу у всей системы
        if combo and any(m in combo for m in MODIFIERS):
            self.hotkey = combo
            self.cfg["hotkey"] = combo
            save_config(self.cfg)
        elif combo:
            self._set_status("need a modifier key", error=True)
        self._render_hotkey()
        # Привязываем не сразу: клавиши ещё зажаты, и свежий хоткей поймал бы
        # то же самое нажатие, мгновенно запустив запись. Флаг снимаем вместе
        # с привязкой, чтобы в паузе toggle тоже не срабатывал.
        self.after(600, self._rearm_hotkey)

    def _rearm_hotkey(self):
        self._bind_hotkey()
        self.capturing = False

    # --- запись --------------------------------------------------------------
    def toggle(self):
        if self.busy or self.capturing or self.shutting_down:
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
        # запоминаем, куда диктуем: пока идёт распознавание, фокус может уехать
        self.target_window = None if foreground_is_self() else foreground_window()
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
        hours, rest = divmod(sec, 3600)
        clock = f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours \
            else f"{rest // 60}:{rest % 60:02d}"
        self._set_status(f"recording {clock}")
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

    def _transcribe_piece(self, audio):
        """Один кусок. Если закодированный файл не влезает в лимит Groq,
        делим пополам — иначе запрос вернёт ошибку и кусок пропадёт."""
        buf = encode_flac(audio)
        if buf.getbuffer().nbytes > MAX_UPLOAD_BYTES and \
                len(audio) > SAMPLE_RATE * 60:
            middle = len(audio) // 2
            halves = [self._transcribe_piece(audio[:middle]),
                      self._transcribe_piece(audio[middle:])]
            return " ".join(h for h in halves if h)
        return transcribe_retrying(
            buf, self.api_key, self.lang,
            on_wait=lambda reason, delay: self.after(
                0, self._set_status, f"retry in {delay}s · {reason}"))

    def _work(self, audio):
        """Длинная запись уходит кусками по очереди. Каждый готовый кусок
        сразу пишется на диск, поэтому обрыв на середине не стоит всей
        записи."""
        done, path = [], None
        try:
            parts = split_audio(audio)
            for index, part in enumerate(parts, 1):
                if len(parts) > 1:
                    self.after(0, self._set_status,
                               f"transcribing {index}/{len(parts)}")
                text = self._transcribe_piece(part)
                if text:
                    done.append(text)
                    if len(parts) > 1:
                        path = append_partial(path, text)
            self.after(0, self._done, " ".join(done).strip(), path)
        except Exception as e:
            rescue = " ".join(done).strip()
            if not rescue:                      # ни одного куска не вышло —
                path = save_audio(audio)        # сохраняем хотя бы звук
            self.after(0, self._fail, str(e), rescue, path)

    def _done(self, text, path=None):
        self.busy = False
        if not text:
            self._set_status("no speech")
            return
        if path is None and len(text) > LONG_TEXT_CHARS:
            path = save_transcript(text)
        self._copy(text)
        # Вставляем только в то окно, откуда начинали диктовать. Пока шло
        # распознавание, фокус мог уехать в чужой чат — туда текст не полетит.
        if foreground_is_self():
            self._set_status("copied")
        elif self.target_window and foreground_window() != self.target_window:
            self._set_status("copied · window changed")
        else:
            keyboard.send("ctrl+v")
            self._set_status("pasted")
        self._add_history(text, path)

    def _fail(self, message, rescue="", path=None):
        """Даже когда запрос провалился, сделанное не пропадает: расшифрованные
        куски идут в буфер и в историю, а без них на диск ложится звук."""
        self.busy = False
        if rescue:
            self._copy(rescue)
            self._add_history(rescue, path)
            self._set_status(f"{message} · partial kept", error=True)
        elif path:
            self._add_history(f"[audio saved: {os.path.basename(path)}]", path)
            self._set_status(f"{message} · audio saved", error=True)
        else:
            self._set_status(message, error=True)

    # --- история -------------------------------------------------------------
    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def _add_history(self, text, path=None):
        self.history.insert(0, (datetime.now().strftime("%H:%M"), text, path))
        del self.history[HISTORY_SIZE:]
        self._render_history()

    def _render_history(self):
        for w in self.hist_frame.winfo_children():
            w.destroy()
        if not self.history:
            tk.Label(self.hist_frame, text="—", bg=PAPER, fg=MUTED,
                     font=(self.mono, 9), anchor="w").pack(fill="x")
            return
        for index, (stamp, text, path) in enumerate(self.history):
            if index:
                tk.Frame(self.hist_frame, bg=HAIRLINE, height=1).pack(fill="x")
            row = tk.Frame(self.hist_frame, bg=PAPER, cursor="hand2", pady=8)
            row.pack(fill="x")
            time_lbl = tk.Label(row, text=stamp, bg=PAPER, fg=MUTED,
                                font=(self.mono, 8), anchor="nw", width=6)
            time_lbl.pack(side="left", anchor="n")
            column = tk.Frame(row, bg=PAPER)
            column.pack(side="left", fill="x", expand=True)
            preview = text if len(text) <= PREVIEW_CHARS \
                else text[:PREVIEW_CHARS].rstrip() + "…"
            body = tk.Label(column, text=preview, bg=PAPER, fg=INK,
                            font=(SANS, 10), anchor="w", justify="left",
                            wraplength=self.S(300))
            body.pack(fill="x")
            tiles = [row, time_lbl, column, body]
            if path:
                # длинный текст живёт файлом — показываем объём и даём открыть
                note = tk.Label(column, bg=PAPER, fg=MUTED, font=(self.mono, 8),
                                anchor="w", cursor="hand2",
                                text=f"{len(text)} chars · {os.path.basename(path)}")
                note.pack(fill="x", pady=(self.S(3), 0))
                note.bind("<Button-1>", lambda _e, p=path: self._open_file(p))
                tiles.append(note)
            for w in tiles:
                if not path or w is not tiles[-1]:
                    w.bind("<Button-1>", lambda _e, t=text: self._copy_again(t))
                w.bind("<Enter>", lambda _e, ws=tiles:
                       [x.config(bg=STAGE) for x in ws])
                w.bind("<Leave>", lambda _e, ws=tiles:
                       [x.config(bg=PAPER) for x in ws])

    def _copy_again(self, text):
        self._copy(text)
        self.hint.config(text="copied")
        self.after(1500, lambda: self.hint.config(text=""))

    def _open_file(self, path):
        try:
            os.startfile(path)
        except Exception:
            self.hint.config(text="file missing")
            self.after(2000, lambda: self.hint.config(text=""))

    # --- жизнь в трее ---------------------------------------------------------
    def _build_tray(self):
        """Значок в области уведомлений. Пока он есть, закрытие окна не
        выключает приложение: хоткей продолжает работать в фоне."""
        try:
            import pystray
            from make_icon import render
        except Exception:
            return None
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Open Groqer", lambda: self.after(0, self._show),
                                 default=True),
                pystray.MenuItem("Quit", lambda: self.after(0, self._quit)),
            )
            icon = pystray.Icon("groqer", render(32), "Groqer", menu)
            threading.Thread(target=icon.run, daemon=True).start()
            return icon
        except Exception:
            return None

    def _show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self):
        """Крестик прячет окно, а не выключает приложение — выход через трей."""
        if self.tray:
            self.withdraw()
            if not self.hinted_tray:
                self.hinted_tray = True
                try:
                    # Имя приложения Windows ставит сверху сама, поэтому в
                    # заголовке — состояние: пустой заголовок библиотека
                    # заменила бы именем значка, и «Groqer» шёл бы дважды.
                    self.tray.notify(
                        f"{pretty_hotkey(self.hotkey)} works in any app, "
                        "even with this window closed", "Running in background")
                except Exception:
                    pass
            return
        self._quit()

    def _quit(self):
        """Выходим, только когда терять нечего: активную запись сохраняем
        звуком на диск, а начатую расшифровку дожидаемся — её результат
        иначе придёт в уже уничтоженное окно и пропадёт."""
        self.shutting_down = True
        if self.recording:
            self.recording = False
            self.overlay.hide()
            if self.tick_job:
                self.after_cancel(self.tick_job)
                self.tick_job = None
            audio, seconds = self.recorder.stop()
            if audio is not None and seconds >= MIN_SECONDS:
                path = save_audio(audio)
                if path:
                    self._notify_tray(f"Recording saved: {os.path.basename(path)}",
                                      "Saved before exit")

        if self.busy and self.quit_waits < QUIT_MAX_WAITS:
            if not self.quit_waits:
                self._show()
            self.quit_waits += 1
            self._set_status("finishing transcription…")
            self.after(500, self._quit)
            return

        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.destroy()

    def _notify_tray(self, message, title):
        try:
            if self.tray:
                self.tray.notify(message, title)
        except Exception:
            pass


if __name__ == "__main__":
    set_app_id()
    enable_dpi_awareness()
    App().mainloop()
