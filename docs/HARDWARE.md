# Vigil — proof-of-concept build

Rough and functional, not pretty. The goal is to find out whether this thing is
actually useful before spending money or a month on it.

**The order matters.** Phase 0 costs nothing and answers the only question that
matters. Do not skip it and do not order parts before finishing it.

---

## Phase 0 — Prove it works with no hardware at all

**Time: 20 minutes. Cost: $0.**

You already have everything you need. `poc/notify.py` and `poc/watch.py` are written.

### 1. Point Claude Code's hooks at the script

> **This is a file edit, not a terminal command.** Do not paste this into
> PowerShell. Open the file in a text editor and add the block below.
> (Only step 2 is a command you run.)

Open `%USERPROFILE%\.claude\settings.json`. If it has no `hooks` key,
add this. If it already has one, merge these entries in.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python \"C:\\Users\\you\\vigil\\poc\\notify.py\" working" }] }
    ],
    "PreToolUse": [
      { "hooks": [{ "type": "command", "command": "python \"C:\\Users\\you\\vigil\\poc\\notify.py\" working" }] }
    ],
    "PermissionRequest": [
      { "hooks": [{ "type": "command", "command": "python \"C:\\Users\\you\\vigil\\poc\\notify.py\" blocked" }] }
    ],
    "Notification": [
      { "hooks": [{ "type": "command", "command": "python \"C:\\Users\\you\\vigil\\poc\\notify.py\" question" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "python \"C:\\Users\\you\\vigil\\poc\\notify.py\" done" }] }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "python \"C:\\Users\\you\\vigil\\poc\\notify.py\" idle" }] }
    ]
  }
}
```

### 2. Open a second terminal and run the fake device

```
python "%USERPROFILE%\vigil\Code\poc\watch.py"
```

Put that window on a second monitor, or off to the side.

### 3. Use Claude Code normally for a week

**Done looks like:** the watch window changes colour and state as Claude works,
shows the project name, and counts up how long it's been waiting on you.

### 4. The only question that matters

After a week, answer honestly: **did you glance at it?**

- **Yes** → the concept is real. Build the hardware. Continue to Phase 1.
- **No** → stop here. You just saved $60 and a month. That is a good outcome.

`log.txt` will tell you the truth too — count how many `tier5`/`tier7` lines there
are and how long the gaps were. That number is the actual size of the problem.

---

## Phase 1 — Order parts

**Cost: ~$47 budget, ~$70 beginner-friendly.**

Get the beginner-friendly set for a first build. Adafruit boards cost a few
dollars more and have first-class CircuitPython support and real documentation,
which will save you hours.

| Part | Search for | Budget | Easy |
|---|---|---|---|
| Microcontroller | **Adafruit ESP32-S3 Feather** (or generic "ESP32-S3 DevKitC-1") | $8 | $18 |
| Round screen | "1.28 inch round LCD GC9A01 SPI module" (Waveshare) | $12 | $12 |
| LED ring | "NeoPixel Ring 16 WS2812B" | $8 | $12 |
| Rotary encoder | "KY-040 rotary encoder module" (has pull-ups built in) | $3 | $5 |
| Microphone | "INMP441 I2S microphone module" — Phase 5, order later | $4 | $6 |
| Breadboard + jumpers | "solderless breadboard jumper wire kit" | $10 | $12 |
| USB-C cable | data cable, **not** charge-only | — | — |

**The one part that trips people:** many cheap USB-C cables are charge-only and
carry no data. If the board never appears on your computer, try another cable
before assuming the board is dead.

Why ESP32-S3 specifically: it has native USB, so one chip can be a **mouse**
(keeps the machine awake) and a **serial port** (receives status) at the same
time, over one cable. Older ESP32 and most Arduinos cannot do this.

---

## Phase 2 — Get the board talking

**Time: 1 hour.**

1. Download CircuitPython for your exact board from `circuitpython.org/downloads`
2. Plug the board in, double-tap its RESET button — a USB drive appears
3. Drag the `.uf2` file onto that drive. It reboots as a drive called `CIRCUITPY`
4. Open `CIRCUITPY/code.py` in any text editor, paste:

```python
import board, digitalio, time
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
while True:
    led.value = not led.value
    time.sleep(0.5)
```

5. Save. It runs immediately — no compiling, no upload button.

**Done looks like:** the onboard LED blinks.

CircuitPython is the right choice here because you edit a file and save it.
There is no build step to get wrong.

---

## Phase 3 — Ring responds to real agent events

**Time: an evening. This is the moment it becomes real.**

### Wire the NeoPixel ring

| Ring pin | Board pin |
|---|---|
| DIN / IN | GPIO 5 |
| 5V / VCC | USB / VBUS (**5V, not 3.3V**) |
| GND | GND |

> Confirm pin names against your board's silkscreen — numbering varies between
> ESP32-S3 boards. Any free GPIO works; just match it in the code.

### On the board — `code.py`

```python
import board, neopixel, usb_cdc, time

pixels = neopixel.NeoPixel(board.IO5, 16, brightness=0.3, auto_write=False)
serial = usb_cdc.data

COLORS = {
    1: (20, 20, 20),     2: (0, 60, 255),   3: (0, 255, 120),
    4: (255, 170, 0),    5: (255, 90, 0),   6: (255, 0, 0),
    7: (255, 0, 0),
}

tier = 1
buf = ""
while True:
    if serial and serial.in_waiting:
        buf += serial.read(serial.in_waiting).decode()
        if "\n" in buf:
            line, buf = buf.split("\n", 1)
            try:
                tier = int(line.split("|")[0])
            except Exception:
                pass

    c = COLORS.get(tier, COLORS[1])
    if tier == 7:                      # fast strobe
        on = int(time.monotonic() * 6) % 2
        pixels.fill(c if on else (0, 0, 0))
    elif tier >= 4:                    # pulse
        import math
        b = 0.4 + 0.6 * abs(math.sin(time.monotonic() * 2))
        pixels.fill(tuple(int(v * b) for v in c))
    else:
        pixels.fill(c)
    pixels.show()
    time.sleep(0.03)
```

### Enable the data serial channel — `boot.py` on `CIRCUITPY`

```python
import usb_cdc
usb_cdc.enable(console=True, data=True)
```

Save, then **fully unplug and replug** the board. `boot.py` only runs on power-up.

### On your PC

```
pip install pyserial
```

Find the board's **data** COM port in Device Manager (there will be two — the
data one is usually the second). Then open `poc/notify.py` and set:

```python
SERIAL_PORT = "COM7"    # whatever yours is
```

**Done looks like:** ask Claude to do something. The ring goes blue. It hits a
permission prompt — the ring goes orange and pulses. You approve — it goes green.

If that happens, you have built the product. Everything after this is refinement.

---

## Phase 4 — Screen

**Time: an evening.**

Wire the GC9A01 over SPI:

| Screen | Board |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SCL / SCK | GPIO 12 |
| SDA / MOSI | GPIO 11 |
| CS | GPIO 10 |
| DC | GPIO 9 |
| RST | GPIO 8 |
| BLK | 3V3 |

Use CircuitPython's `displayio` with the `gc9a01` driver from the Adafruit
bundle. Show three lines: state word, project name, elapsed time. The elapsed
time is the part that actually changes behaviour — do not skip it.

**Done looks like:** the screen reads `BLOCKED / your-project / 14m`.

---

## Phase 5 — Keep-awake and the encoder

**Time: an evening.**

### Mouse jiggler (the second job of the same cable)

`boot.py`:
```python
import usb_cdc, usb_hid
usb_cdc.enable(console=True, data=True)
usb_hid.enable((usb_hid.Device.MOUSE,))
```

In `code.py`, every 30 seconds:
```python
import usb_hid
from adafruit_hid.mouse import Mouse
mouse = Mouse(usb_hid.devices)
mouse.move(1, 0); mouse.move(-1, 0)     # net zero, but the OS sees activity
```

**Also do this first, it's free:** Windows Settings → System → Power →
"When I close the lid" → **Do nothing**. A jiggler defeats idle sleep; only that
setting defeats lid-close sleep. Two different problems.

### Encoder

Wire A→GPIO1, B→GPIO2, SW→GPIO3. Use `rotaryio` and `keypad`. Twist cycles
between waiting sessions; press acknowledges and returns the ring to idle.

---

## Phase 6 — Live with it for a week

No code. Just use it.

Keep a note of: how many times it caught something you'd have missed, how many
times it annoyed you, and whether tier 2 (working, blue) is calm enough to ignore.

**If it annoys you more than it helps, the fix is almost always to make tiers 1–4
dimmer and slower, not to add features.**

---

## Phase 7 — Only now, the enclosure

You now know the real dimensions of every component. Measure them, then use
Prompt 2 in `Vigil.md`, and use `Design/CAD/Vigil-Concept.stl` as the
silhouette reference.

Do not design the box before this point. You will print three that don't fit.

---

## When something breaks

| Symptom | Cause |
|---|---|
| Board doesn't appear at all | Charge-only USB cable. Try another. |
| `boot.py` changes do nothing | You reset instead of power-cycling. Unplug fully. |
| No serial data arriving | You're on the console port, not the data port. Try the other COM. |
| Ring is white and blinding | Missing `brightness=0.3`, or wired to 3.3V instead of 5V. |
| Claude Code feels slow or errors | A hook is hanging. `notify.py` always exits 0 — if you edit it, keep that. |
| Ring stuck on one colour | Hook isn't firing. Check `log.txt` — if it's empty, the settings.json path is wrong. |

---

## What this costs you

| | Time | Money |
|---|---|---|
| Phase 0 | 20 min + a week of noticing | $0 |
| Phases 1–5 | 3–4 evenings | ~$60 |
| Phase 6 | a week | $0 |
| Phase 7 | a weekend + prints | ~$10 filament |

**Phase 0 is the whole decision.** Everything after it is just execution.
