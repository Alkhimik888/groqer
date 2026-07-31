# Groqer

Push-to-talk dictation for Windows. Press **Ctrl+Space**, speak, press it again — the text
appears in whatever window you were typing into. Works in any application — browser, editor,
chat, terminal — in any of the 100 languages `whisper-large-v3` supports.

![Groqer window](docs/screenshot.png)

## Why cloud transcription

Groqer sends your audio to Groq instead of running a model on your machine:

- **Fast** — roughly 200× real time; a short phrase comes back in under a second.
- **Accurate on Russian** — `whisper-large-v3` is far more accurate than the small models a
  laptop can run locally, especially outside English.
- **Nothing to install or maintain** — no multi-gigabyte model, no GPU, no updates.
- **Free in practice** — the free tier is far above what everyday dictation uses (see
  [Limits](#limits)).

Honestly: your audio leaves the machine. It goes directly to `api.groq.com` over HTTPS,
nowhere else, and nothing is stored server-side by the app.

## Getting a free API key

1. Go to [console.groq.com](https://console.groq.com) and sign up — Google, GitHub, or
   email. No credit card.
2. Go to [console.groq.com/keys](https://console.groq.com/keys).
3. Click **Create API Key**, give it any name, confirm.
4. **Copy the key immediately** — it starts with `gsk_` and is shown only once.

## Install

Requirements: Windows 10 or 11, and [Python 3.11 or newer](https://www.python.org/downloads/)
(during installation tick **Add Python to PATH**).

Download this repository, open PowerShell in its folder, and run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe voice_typing.py
```

The last line starts the app. Use `pythonw.exe`, not `python.exe` — it runs without a console
window.

**Desktop shortcut** — right-click the desktop → New → Shortcut → paste the full path to
`.venv\Scripts\pythonw.exe`, a space, then the full path to `voice_typing.py` in quotes. In
the shortcut's Properties → Change Icon, point it at `groqer.ico`.

**Start with Windows (optional)** — press `Win+R`, type `shell:startup`, and drop a copy of
that shortcut into the folder that opens.

## First run

The window shows a **groq key** field. Paste your `gsk_…` key and press **ok** — the field
disappears, and the key is saved to `groq.env` next to the script (excluded from git, so it
can't end up in a repository by accident). A `GROQ_API_KEY` environment variable also works
and takes priority over the file.

Windows will ask for microphone permission once — allow it.

## Daily use

Press **Ctrl+Space** to start recording, press it again to stop. A small translucent
microphone follows your mouse cursor while you're recording.

When you stop, the text is always copied to the clipboard, and pasted into the window you
dictated from. The status line tells you which happened:

- **`pasted`** — copied, and pasted back into your window.
- **`copied`** — nothing to paste into (Groqer's own window was in front when you stopped).
- **`copied · window changed`** — you switched windows while it was still transcribing, so
  Groqer left the text in the clipboard instead of pasting it somewhere wrong.

## Features

- **Hotkey** — click the hotkey line under the button, then press any new combination. It
  applies immediately and survives restarts. A modifier (Ctrl, Alt, Shift, or Win) is
  required.
- **Language** — the dropdown lists every language `whisper-large-v3` supports, with
  auto-detect, Russian, and English pinned to the top. Picking **English** while you speak
  Russian doesn't just do worse — it **translates** instead of transcribing. Use auto-detect
  or your real language.
- **History** — the last 5 transcripts are listed; click one to copy it again.
- **Tray icon** — the app lives here. Closing the window does not quit it — the hotkey keeps
  working. Use **Quit** in the tray menu to actually exit.

## Long recordings

There is no practical length limit — a lecture, an interview, a two-hour meeting all work.

- Long recordings are split into ~15-minute pieces at the nearest quiet moment (so no word
  is cut in half), transcribed separately, and joined back together.
- Transcripts longer than about a minute of speech are saved to `transcripts\*.txt`, with a
  link to the file in the history list.
- A single recording is capped at 7 hours.
- If transcription fails partway through, the parts already done are kept, and the raw audio
  is saved as a `.flac` file, so nothing is lost.

## Limits

Groq's free tier, at the time of writing:

| | Free tier |
|---|---|
| Requests | 20/minute, 2000/day |
| Audio | 7200 seconds/hour |
| Upload | 25 MB/request |

Dictation never gets near these.

## Troubleshooting

- **`no groq key`** — paste your key into the field at the bottom of the window.
- **`key rejected`** — the key is wrong or revoked; create a new one at
  [console.groq.com/keys](https://console.groq.com/keys).
- **Rate limit** — you've hit Groq's 20-requests-per-minute cap; wait a minute and try again.
- **`hotkey busy`** — another app already holds that combination; click the hotkey line and
  pick a different one.
- **`no mic`** — Windows didn't grant microphone access, or nothing is plugged in; check
  Settings → Privacy → Microphone.
- **Text went to the clipboard but wasn't pasted** — Groqer's own window was in front, or you
  switched windows mid-transcription. The text is always safe in the clipboard — paste it
  manually with Ctrl+V.
- **Nothing happens on the hotkey / app seems gone** — check the tray for the yellow
  microphone icon; closing the window doesn't close the app.

## License

MIT — see [LICENSE](LICENSE).
