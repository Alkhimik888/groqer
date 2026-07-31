# Groqer

Dictation for Windows. Press **Ctrl+Space**, speak, press it again — your words appear
in whatever window you were typing in. Works in any application: browser, editor, chat,
terminal.

![Groqer window](docs/screenshot.png)

Transcription runs on Groq's `whisper-large-v3`. It is accurate on Russian, not only on
English, and the free tier covers everyday dictation without ever charging you.

---

## Why cloud transcription, and not a local model

Every dictation tool either runs a speech model on your own machine or sends audio to a
service. Groqer sends it, and here is what that buys you:

- **Speed.** Groq transcribes at roughly 200× real time. A 30-second phrase comes back in
  well under a second. A local model on a laptop without a discrete GPU takes longer than
  the recording itself.
- **Accuracy on non-English speech.** `whisper-large-v3` has a ~10% word error rate across
  languages. The small models that run comfortably on a laptop are noticeably worse, and
  the gap widens outside English.
- **Nothing to install or maintain.** No 1.5–3 GB model files, no CUDA, no updates. The app
  is a few hundred kilobytes of Python.
- **Your laptop stays cool.** Transcription does not touch your CPU, so nothing spins up and
  the battery is unaffected.
- **It costs nothing in practice.** See [Limits](#limits) — the free tier is far above what
  dictation consumes.

The trade-off is honest: your audio leaves the machine. It goes directly from your computer
to `api.groq.com` over HTTPS and nowhere else — there is no server in between, no account,
no telemetry. Nothing is written to disk except transcripts you explicitly get to keep. If
that trade-off is unacceptable for your material, use a local tool instead.

---

## Step 1 — Get a Groq API key

The key is free. No credit card, no paid plan.

1. Open **https://console.groq.com** and sign up. Google, GitHub or email all work.
2. Go to **https://console.groq.com/keys**.
3. Click **Create API Key**, give it any name (for example `groqer`), confirm.
4. **Copy the key immediately.** It starts with `gsk_` and is shown exactly once — after
   you close the dialog it cannot be retrieved, only replaced with a new one.

That is the whole process; there is nothing to configure in the console.

---

## Step 2 — Install

You need Windows 10 or 11 and [Python 3.11 or newer](https://www.python.org/downloads/)
(during installation tick **Add Python to PATH**).

Download this repository, open PowerShell in its folder and run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the app:

```powershell
.venv\Scripts\pythonw.exe voice_typing.py
```

Use `pythonw.exe`, not `python.exe` — the first one runs without a console window.

**Make a shortcut** so you do not retype that: right-click the desktop → New → Shortcut,
paste the full path to `.venv\Scripts\pythonw.exe` followed by the full path to
`voice_typing.py` in quotes. Then open the shortcut's Properties → Change Icon → point it
at `groqer.ico`.

To start it with Windows, press `Win+R`, type `shell:startup`, and drop a copy of that
shortcut into the folder that opens.

---

## Step 3 — First run: paste the key

On the first launch the window shows a field labelled **groq key** at the bottom.

Paste the `gsk_…` key into it and press **ok**. The field disappears and never comes back —
the key is saved to `groq.env` next to the script, and that file is excluded from git so it
cannot end up in a repository by accident.

If you prefer, set a `GROQ_API_KEY` environment variable instead; it takes priority over the
file.

Windows will ask for microphone permission the first time you record. Allow it.

---

## Daily use

**Press Ctrl+Space, speak, press Ctrl+Space again.** That is the whole workflow.

While recording, a small translucent microphone sits next to your mouse cursor and breathes
slowly — a reminder that you are live, visible from the corner of your eye without looking
away from your work. The status in the window shows elapsed time.

When you stop, the text is transcribed and:

- **copied to the clipboard** — always, without exception;
- **pasted into the window you were working in** — if that window is not Groqer itself.

The status line says which happened: `pasted` or `copied`. If Groqer's own window was in
front there was nowhere to paste, so the text waits in the clipboard.

You can also click the yellow **Speak** button instead of using the keyboard.

---

## What the interface does

**The hotkey line under the button** shows the current combination and `click to change`.
Click it, press any new combination, and it takes effect immediately and survives restarts.
A modifier (Ctrl, Alt, Shift or Win) is required — without one the app would take an
ordinary key away from the whole system.

**The language dropdown** at the bottom lists every language `whisper-large-v3` supports,
with `auto-detect`, Russian and English pinned to the top.

> Pick the language you actually speak. Telling Whisper "English" while speaking Russian does
> not degrade gracefully — it **translates** instead of transcribing, and you get English text
> back. `auto-detect` is safe; a wrong explicit choice is not.

**The recent list** keeps your last five transcripts. Click any of them to copy it again.

**The tray icon** (bottom-right, next to the clock) is where the app lives. Closing the
window does not quit it: the hotkey keeps working and the icon stays. Double-click the icon
to bring the window back, or use **Quit** in its menu to actually exit.

---

## Long recordings

There is no practical length limit. A lecture, an interview, a two-hour meeting — all work.

- Recordings longer than 30 minutes are **split into half-hour pieces** automatically, each
  sent separately, and the texts joined back together. Cut points are nudged to the nearest
  pause within ±12 seconds so no word is sliced in half. The status shows progress:
  `transcribing 2/4`.
- Transcripts longer than about **900 characters — roughly a minute of speech** — are saved
  to `transcripts\YYYY-MM-DD_HH-MM-SS.txt` next to the app. A minute of speech is already 22
  lines of text; it will not fit in a small window, and losing it would be worse than
  cluttering the folder. The recent list shows the first 160 characters plus a line like
  `9800 chars · 2026-07-31_14-32-10.txt` — click that line to open the file, click the entry
  itself to copy the full text.
- A single recording is capped at **7 hours**, purely so one session cannot exhaust the daily
  free allowance in one go.

---

## Limits

Groq's free tier, at the time of writing:

| | Free tier |
|---|---|
| Requests | 20 per minute, 2000 per day |
| Audio | 7200 seconds (2 hours) per hour, 28800 seconds (8 hours) per day |
| Upload size | 25 MB per request |

Groqer records 16 kHz mono and encodes to FLAC, which is about 10 KB per second — so 25 MB
is roughly 40 minutes of speech, and the half-hour split keeps every request comfortably
inside that.

For dictation these ceilings are unreachable. They start to matter only if you transcribe
several hours of recordings in one day.

---

## If something goes wrong

**`no groq key`** — the key was not found. Paste it into the field at the bottom of the
window.

**`key rejected`** — the key is wrong or was revoked. Create a new one at
[console.groq.com/keys](https://console.groq.com/keys).

**`rate limit, wait a minute`** — you hit 20 requests per minute. Wait and repeat.

**`hotkey busy`** — another application already holds that combination. Click the hotkey
line and choose a different one.

**`no mic`** — Windows did not give access to the microphone, or no input device is
connected. Check Settings → Privacy → Microphone.

**Text goes to the wrong window** — the transcript is pasted into whatever window is focused
when transcription *finishes*, not when it starts. If you click elsewhere while it works, the
text follows your click. It is always in the clipboard as well, so nothing is lost.

**Nothing happens on the hotkey** — check that the app is still running: look for the yellow
microphone icon in the tray. If the window was closed, the app is still there.

---

## How it works

Audio is captured at 16 kHz mono and encoded to FLAC in memory — lossless, and small enough
that uploads are quick. The recording never touches disk.

The recording indicator is a layered window drawn with `UpdateLayeredWindow`. That is the
only way to get a smooth edge together with independent transparency for the plate and the
mark: a colour-key transparent window produces a ragged outline, and a uniform alpha washes
the microphone out along with its background. The window ignores clicks and never takes
focus, so it cannot interfere with what you are typing into.

The app declares itself DPI-aware and sets its own `AppUserModelID`. Without the first,
Windows renders the window at 96 dpi and stretches the result, which looks blurry on a
scaled display. Without the second, the taskbar files the window under `pythonw.exe` and
shows Python's icon instead of ours.

`make_icon.py` regenerates `groqer.ico`. Every size is drawn at its own resolution instead
of being downsampled from one large image — at 16 pixels an antialiased reduction turns the
microphone into a smudge.

---

## Design

The interface follows the "editorial terminal" system: a single accent (`#ffdc2e`, fill
only, always carrying `#14140f` on top), hairline rules, zero corner radius, monospace
reserved for data — timings, states, key names, character counts — and prose set lowercase
in a grotesque.

---

## License

MIT — see [LICENSE](LICENSE).
