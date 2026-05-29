# CLD1010LP Control GUI

User Manual and Software Documentation

Python GUI for controlling the Thorlabs CLD1010LP laser controller and AD2 waveform modulation.

---


https://github.com/user-attachments/assets/a62e0d1b-bb71-436c-a899-40fd2bc284b3


# Features

This program provides a simple GUI for:

- TEC temperature control
- Laser diode current control
- Current limit protection
- Pulse sequence generation
- Spike train generation
- PPF (Paired Pulse Facilitation) testing
- Time-based pulse sequences
- AD2 hardware waveform modulation
- Real-time current and TEC monitoring

---

# Hardware Requirements

## Required Devices

- Thorlabs CLD1010LP
- Digilent Analog Discovery 2 (AD2) *(optional for modulation mode)*
- USB connection

---

# Software Requirements

## 1. Python

Recommended version:

```text
Python 3.10+
```

Download:

- https://www.python.org/downloads/windows/

During installation, make sure to check:

```text
Add Python to PATH
```

---

## 2. NI-VISA

Required for CLD1010LP communication.

Download:

- https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html

After installation, verify that the instrument appears in:

```text
NI MAX (Measurement & Automation Explorer)
```

---

## 3. Digilent WaveForms

Required for AD2 support.

Download:

- https://digilent.com/reference/software/waveforms/waveforms-3/start

This installs the DWF runtime library automatically.

---

## 4. Python Packages

Install required packages:

```bash
pip install pyvisa
```

---

# File Structure

```text
project/
│
├── cld1010lp_gui.py
├── README.md
└── screenshots/
```

---

# Hardware Set up and Running the Program

1. Open the Laser Power, and switch the key to unlock
2. Connect Laser and AD2 to your computer
3. Connect Laser and AD2(black wire to ground; red wire to W1)
4. Open Command Prompt inside the project folder:
```bash
python cld1010lp_gui_windows.py
```

---

# Connecting to CLD1010LP

Typical VISA resource:

```text
USB0::0x1313::0x804F::XXXXXXXX::INSTR
```

Steps:

1. Click `Connect` and `Connect AD2`
2. Verify IDN response appears


---
<img width="1470" height="956" alt="image" src="https://github.com/user-attachments/assets/e6a8d3ba-532e-4099-a344-3ee2b8770dfb" />

# GUI Functions

# TEC Section

Functions:

- Set TEC temperature
- Turn TEC ON/OFF
- Monitor actual temperature

---

# Laser Diode Section

Functions:

- Set current limit
- Set laser current manually
- LD ON/OFF control
- Real-time current monitoring

---

# Sequence Section

Supports:

- Frequency-based pulse generation
- Duty cycle control
- Spike train testing
- PPF testing
- Time-based pulse sequences

Example:

```text
Frequency = 0.5 Hz
Duty = 0.5

→ ON 1 s
→ OFF 1 s
```

---

# AD2 Pulse Control

Supports hardware-generated pulse modulation using AD2.

Functions:

- Hardware pulse waveform generation
- Adjustable frequency
- Adjustable duty cycle
- Adjustable cycle count
- Automatic return to 0 V after waveform completion

---

## Error Recovery Procedure

If an error message appears in the Status/Error panel at the bottom of the GUI:

### Step 1 — Disable Laser Output

Click:

```text
LD OFF
```

---

### Step 2 — Disable TEC

Click:

```text
TEC OFF
```

---

### Step 3 — Clear Error Queue

Click:

```text
Clear Error Queue
```

This sends:

```text
*CLS
```

to clear the CLD1010LP error buffer.

---

### Step 4 — Refresh Status

Click:

```text
Refresh
```

Check whether the error message disappears.

---

### Step 5 — Restart the Laser Controller

If the error remains:

1. Turn OFF LD
2. Turn OFF TEC
3. Disconnect USB from CLD1010LP
4. Wait 5–10 seconds
5. Reconnect USB
6. Launch the GUI again
7. Click Connect

---

### Step 6 — Verify Communication

After reconnecting:

```text
IDN field should display:
Thorlabs,CLD1010LP,...
```

and

```text
Last Error:
0, No error
```

---

### Step 7 — Full Software Restart

If communication still fails:

1. Close the GUI
2. Power cycle the CLD1010LP
3. Restart the computer
4. Reconnect the controller
5. Launch the GUI again

---

### Recommended Recovery Order

```text
LD OFF
↓
TEC OFF
↓
Clear Error Queue
↓
Refresh
↓
Reconnect CLD1010LP
↓
Restart GUI
```

This procedure resolves most communication, VISA, and controller-state errors.

# Notes

- Always set a safe current limit before enabling LD output.
- Ensure TEC is opened before opening LD
- Ensure TEC is stable before high-current operation.
- AD2 modulation may override manual current control depending on wiring configuration.
- Do not exceed the safe current range of your laser diode.
- Always turn LD off when you finish one sequence.
- Close the Laser and lock the key after finishing.

---

# Tested Environment

- Windows 11
- Python 3.10+
- NI-VISA
- Digilent WaveForms SDK

---


