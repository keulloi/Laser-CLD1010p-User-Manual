import threading
import time

from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from ctypes import *
try:
    import pyvisa
except ImportError:
    pyvisa = None


class CLDController:
    def __init__(self):
        self.rm = None
        self.inst = None
        

    def connect(self, resource: str, visa_lib: str | None = None):
        if pyvisa is None:
            raise RuntimeError("pyvisa is not installed. Install it with: python -m pip install pyvisa")

        self.rm = pyvisa.ResourceManager(visa_lib) if visa_lib else pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(resource)
        self.inst.timeout = 8000
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"
        return self.query("*IDN?")

    def is_connected(self) -> bool:
        return self.inst is not None

    def close(self):
        try:
            if self.inst is not None:
                self.write("OUTP1 OFF")
                self.write("OUTP2 OFF")
                self.inst.close()
        except Exception:
            pass
        try:
            if self.rm is not None:
                self.rm.close()
        except Exception:
            pass
        self.inst = None
        self.rm = None

    def write(self, cmd: str):
        if self.inst is None:
            raise RuntimeError("Instrument not connected")
        self.inst.write(cmd)

    def query(self, cmd: str) -> str:
        if self.inst is None:
            raise RuntimeError("Instrument not connected")
        return self.inst.query(cmd).strip()

    def clear(self):
        self.write("*CLS")

    def get_error(self) -> str:
        return self.query("SYST:ERR?")

    def idn(self) -> str:
        return self.query("*IDN?")

    # TEC
    def tec_on(self, set_temp_c: float):
        try:
            self.write("OUTP2 OFF")
            time.sleep(0.1)
        except Exception:
            pass
        self.write("SOUR2:TEMP:SPO {:.3f}".format(set_temp_c))
        self.write("OUTP2 ON")

    def tec_off(self):
        self.write("OUTP2 OFF")

    def tec_state(self) -> int:
        return int(float(self.query("OUTP2?")))

    def tec_temp(self) -> float:
        return float(self.query("SENS2:TEMP:DATA?"))

    def tec_setpoint(self) -> float:
        return float(self.query("SOUR2:TEMP:SPO?"))

    # LD
    def ld_enable_current_mode(self):
        self.write("SOUR1:FUNC CURR")

    def ld_on(self):
        # Avoid +20 by setting mode only before output is ON
        self.write("OUTP1 OFF")
        time.sleep(0.05)
        self.ld_enable_current_mode()
        self.write("OUTP1 ON")

    def ld_off(self):
        self.write("OUTP1 OFF")

    def ld_state(self) -> int:
        return int(float(self.query("OUTP1?")))

    def ld_set_current_a(self, amps: float):
        # Do not resend SOUR1:FUNC CURR here
        self.write("SOUR1:CURR:LEV {:.6f}".format(max(0.0, amps)))

    def ld_set_current_limit_a(self, amps: float):
        self.write("SOUR1:CURR:LIM {:.6f}".format(max(0.0, amps)))

    def ld_setpoint_a(self) -> float:
        return float(self.query("SOUR1:CURR:LEV?"))

    def ld_limit_a(self) -> float:
        return float(self.query("SOUR1:CURR:LIM?"))

    def ld_meas_current_a(self) -> float:
        return float(self.query("SENS3:CURR:DATA?"))

class AD2Controller:
    def __init__(self):
        self.dwf = None
        self.hdwf = c_int()
        self.channel = c_int(0)  # W1

    def connect(self):
        self.dwf = cdll.LoadLibrary("dwf.dll")
        ok = self.dwf.FDwfDeviceOpen(c_int(-1), byref(self.hdwf))
        if not ok or self.hdwf.value == 0:
            raise RuntimeError("AD2 not detected.")
        return "AD2 connected"

    def close(self):
        try:
            self.set_voltage(0.0)
            self.dwf.FDwfAnalogOutConfigure(self.hdwf, self.channel, c_bool(False))
            self.dwf.FDwfDeviceCloseAll()
        except Exception:
            pass

    def set_voltage(self, volts):
        if self.dwf is None or self.hdwf.value == 0:
            raise RuntimeError("AD2 not connected")

        node = c_int(0)  # carrier node
        self.dwf.FDwfAnalogOutNodeEnableSet(self.hdwf, self.channel, node, c_bool(True))
        self.dwf.FDwfAnalogOutNodeFunctionSet(self.hdwf, self.channel, node, c_int(0))  # DC
        self.dwf.FDwfAnalogOutNodeOffsetSet(self.hdwf, self.channel, node, c_double(volts))
        self.dwf.FDwfAnalogOutConfigure(self.hdwf, self.channel, c_bool(True))
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CLD1010LP Control")
        self.geometry("980x620")
        self.resizable(True, True)

        self.ctrl = CLDController()
        self.ad2 = AD2Controller()
        self.ad2_thread = None

        self.ad2_current_mA_var = tk.DoubleVar(value=70.0)
        self.ad2_freq_var = tk.DoubleVar(value=1.0)
        self.ad2_cycles_var = tk.IntVar(value=10)
        self.ad2_duty_var = tk.DoubleVar(value=0.5)
        self.polling = False
        self.sequence_thread = None
        self.stop_flag = False

        self.resource_var = tk.StringVar(value="USB0::0x1313::0x804F::M01296178::INSTR")
        self.visa_var = tk.StringVar(value="")
        self.idn_var = tk.StringVar(value="Not connected")
        self.status_var = tk.StringVar(value="Idle")

        self.tec_set_var = tk.DoubleVar(value=25.0)
        self.tec_temp_var = tk.StringVar(value="--")
        self.tec_state_var = tk.StringVar(value="OFF")

        self.ld_current_mA_var = tk.DoubleVar(value=0.0)
        self.ld_limit_mA_var = tk.DoubleVar(value=80.0)
        self.ld_meas_mA_var = tk.StringVar(value="--")
        self.ld_state_var = tk.StringVar(value="OFF")
        self.err_var = tk.StringVar(value="--")

        self.seq_peak_var = tk.DoubleVar(value=80.0)
        self.seq_freq_var = tk.DoubleVar(value=1.0)
        self.seq_cycles_var = tk.IntVar(value=10)
        self.seq_duty_var = tk.DoubleVar(value=0.5)
        self.seq_on_time_var = tk.DoubleVar(value=1.0)
        self.seq_off_time_var = tk.DoubleVar(value=1.0)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        connect_frame = ttk.LabelFrame(self, text="Connection")
        connect_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(connect_frame, text="Resource").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(connect_frame, textvariable=self.resource_var, width=42).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(connect_frame, text="VISA library (optional)").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(connect_frame, textvariable=self.visa_var, width=26).grid(row=0, column=3, sticky="w", **pad)
        ttk.Button(connect_frame, text="Connect", command=self.connect).grid(row=0, column=4, **pad)
        ttk.Button(connect_frame, text="Disconnect", command=self.disconnect).grid(row=0, column=5, **pad)
        ttk.Label(connect_frame, text="IDN").grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(connect_frame, textvariable=self.idn_var).grid(row=1, column=1, columnspan=5, sticky="w", **pad)

        tec_frame = ttk.LabelFrame(self, text="TEC")
        tec_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(tec_frame, text="Set Temp (°C)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(tec_frame, textvariable=self.tec_set_var, width=10).grid(row=0, column=1, sticky="w", **pad)
        ttk.Button(tec_frame, text="TEC ON", command=self.tec_on).grid(row=0, column=2, **pad)
        ttk.Button(tec_frame, text="TEC OFF", command=self.tec_off).grid(row=0, column=3, **pad)
        ttk.Label(tec_frame, text="Actual Temp").grid(row=0, column=4, sticky="w", **pad)
        ttk.Label(tec_frame, textvariable=self.tec_temp_var).grid(row=0, column=5, sticky="w", **pad)
        ttk.Label(tec_frame, text="State").grid(row=0, column=6, sticky="w", **pad)
        ttk.Label(tec_frame, textvariable=self.tec_state_var).grid(row=0, column=7, sticky="w", **pad)

        ld_frame = ttk.LabelFrame(self, text="Laser Diode (LP only)")
        ld_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(ld_frame, text="Current Limit (mA)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(ld_frame, textvariable=self.ld_limit_mA_var, width=10).grid(row=0, column=1, sticky="w", **pad)
        ttk.Button(ld_frame, text="Apply Limit", command=self.apply_limit).grid(row=0, column=2, **pad)

        ttk.Label(ld_frame, text="Set Current (mA)").grid(row=1, column=0, sticky="w", **pad)
        scale = ttk.Scale(ld_frame, from_=0.0, to=80.0, variable=self.ld_current_mA_var,
                          orient="horizontal", length=320)
        scale.grid(row=1, column=1, columnspan=3, sticky="we", **pad)
        ttk.Entry(ld_frame, textvariable=self.ld_current_mA_var, width=10).grid(row=1, column=4, sticky="w", **pad)
        ttk.Button(ld_frame, text="Apply Current", command=self.apply_current).grid(row=1, column=5, **pad)

        ttk.Button(ld_frame, text="LD ON", command=self.ld_on).grid(row=2, column=0, **pad)
        ttk.Button(ld_frame, text="LD OFF", command=self.ld_off).grid(row=2, column=1, **pad)
        ttk.Button(ld_frame, text="Set 0 mA", command=lambda: self.quick_current(0.0)).grid(row=2, column=2, **pad)
        ttk.Button(ld_frame, text="Set 80 mA", command=lambda: self.quick_current(80.0)).grid(row=2, column=3, **pad)
        ttk.Label(ld_frame, text="Measured Current (mA)").grid(row=2, column=4, sticky="e", **pad)
        ttk.Label(ld_frame, textvariable=self.ld_meas_mA_var).grid(row=2, column=5, sticky="w", **pad)
        ttk.Label(ld_frame, text="LD State").grid(row=2, column=6, sticky="w", **pad)
        ttk.Label(ld_frame, textvariable=self.ld_state_var).grid(row=2, column=7, sticky="w", **pad)

        seq_frame = ttk.LabelFrame(self, text="Sequences")
        seq_frame.pack(fill="x", padx=10, pady=8)

        ttk.Label(seq_frame, text="Peak Current (mA)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(seq_frame, textvariable=self.seq_peak_var, width=10).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(seq_frame, text="Frequency (Hz)").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(seq_frame, textvariable=self.seq_freq_var, width=10).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(seq_frame, text="Cycles").grid(row=0, column=4, sticky="w", **pad)
        ttk.Entry(seq_frame, textvariable=self.seq_cycles_var, width=10).grid(row=0, column=5, sticky="w", **pad)
        ttk.Label(seq_frame, text="Duty (0~1)").grid(row=0, column=6, sticky="w", **pad)
        ttk.Entry(seq_frame, textvariable=self.seq_duty_var, width=10).grid(row=0, column=7, sticky="w", **pad)

        ttk.Button(seq_frame, text="Run Sequence", command=self.run_sequence).grid(row=0, column=8, **pad)
        ttk.Button(seq_frame, text="STOP", command=self.stop_sequence).grid(row=0, column=9, **pad)

        ttk.Button(seq_frame, text="80→0 Sweep", command=self.run_sweep_sequence).grid(row=1, column=0, columnspan=2, **pad)
        ttk.Button(seq_frame, text="PPF", command=self.run_ppf_sequence).grid(row=1, column=2, columnspan=2, **pad)
        ttk.Button(seq_frame, text="Spike Train", command=self.run_spike_train).grid(row=1, column=4, columnspan=2, **pad)
        ttk.Label(seq_frame, text="ON time (s)").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(seq_frame, textvariable=self.seq_on_time_var, width=10).grid(row=2, column=1, **pad)

        ttk.Label(seq_frame, text="OFF time (s)").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(seq_frame, textvariable=self.seq_off_time_var, width=10).grid(row=2, column=3, **pad)

        ttk.Button(seq_frame, text="Run Time Sequence", command=self.run_time_sequence).grid(row=2, column=4, columnspan=2, **pad)

        ad2_frame = ttk.LabelFrame(self, text="AD2 Pulse Control")
        ad2_frame.pack(fill="x", padx=10, pady=8)

        ttk.Label(ad2_frame, text="Target Current (mA)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(ad2_frame, textvariable=self.ad2_current_mA_var, width=10).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(ad2_frame, text="Frequency (Hz)").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(ad2_frame, textvariable=self.ad2_freq_var, width=10).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(ad2_frame, text="Cycles").grid(row=0, column=4, sticky="w", **pad)
        ttk.Entry(ad2_frame, textvariable=self.ad2_cycles_var, width=10).grid(row=0, column=5, sticky="w", **pad)

        ttk.Label(ad2_frame, text="Duty").grid(row=0, column=6, sticky="w", **pad)
        ttk.Entry(ad2_frame, textvariable=self.ad2_duty_var, width=10).grid(row=0, column=7, sticky="w", **pad)

        ttk.Button(ad2_frame, text="Connect AD2", command=self.connect_ad2).grid(row=1, column=0, **pad)
        ttk.Button(ad2_frame, text="Run AD2 Wave", command=self.run_ad2_hardware_wave).grid(row=1, column=1, columnspan=2, **pad)
        ttk.Button(ad2_frame, text="STOP AD2", command=self.stop_ad2).grid(row=1, column=3, **pad)

        util_frame = ttk.LabelFrame(self, text="Status / Error")
        util_frame.pack(fill="both", expand=True, padx=10, pady=8)
        ttk.Button(util_frame, text="Refresh", command=self.refresh_now).grid(row=0, column=0, **pad)
        ttk.Button(util_frame, text="Clear Error Queue", command=self.clear_errors).grid(row=0, column=1, **pad)
        ttk.Label(util_frame, text="Last Error").grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(util_frame, textvariable=self.err_var).grid(row=1, column=1, columnspan=4, sticky="w", **pad)
        ttk.Label(util_frame, text="Status").grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(util_frame, textvariable=self.status_var).grid(row=2, column=1, columnspan=6, sticky="w", **pad)

    def set_status(self, text: str):
        self.status_var.set(text)

    

    def run_bg(self, func, ok_msg=None):
        def job():
            try:
                func()
                if ok_msg:
                    self.after(0, lambda: self.set_status(ok_msg))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
                self.after(0, lambda: self.set_status("Error"))
        threading.Thread(target=job, daemon=True).start()

    def connect(self):
        resource = self.resource_var.get().strip()
        visa_lib = self.visa_var.get().strip() or None

        def do_connect():
            idn = self.ctrl.connect(resource, visa_lib)
            self.after(0, lambda: self.idn_var.set(idn))
            self.after(0, self.start_polling)

        self.run_bg(do_connect, ok_msg="Connected")

    def disconnect(self):
        self.polling = False
        self.ctrl.close()
        self.idn_var.set("Not connected")
        self.tec_temp_var.set("--")
        self.ld_meas_mA_var.set("--")
        self.tec_state_var.set("OFF")
        self.ld_state_var.set("OFF")
        self.err_var.set("--")
        self.set_status("Disconnected")

    def tec_on(self):
        def f():
            self.ctrl.tec_on(self.tec_set_var.get())
        self.run_bg(f, ok_msg="TEC ON command sent")

    def tec_off(self):
        self.run_bg(self.ctrl.tec_off, ok_msg="TEC OFF")

    def apply_limit(self):
        def f():
            self.ctrl.ld_set_current_limit_a(self.ld_limit_mA_var.get() / 1000.0)
        self.run_bg(f, ok_msg="Current limit applied")

    def apply_current(self):
        def f():
            self.ctrl.ld_set_current_a(self.ld_current_mA_var.get() / 1000.0)
        self.run_bg(f, ok_msg="Current setpoint applied")

    def quick_current(self, mA: float):
        self.ld_current_mA_var.set(mA)
        self.apply_current()

    def ld_on(self):
        self.run_bg(self.ctrl.ld_on, ok_msg="LD ON")

    def ld_off(self):
        self.run_bg(self.ctrl.ld_off, ok_msg="LD OFF")

    def clear_errors(self):
        def f():
            self.ctrl.clear()
            errs = []
            for _ in range(5):
                e = self.ctrl.get_error()
                errs.append(e)
                if "No error" in e or e.startswith(("0,", "+0,")):
                    break
            self.after(0, lambda: self.err_var.set(" | ".join(errs)))
        self.run_bg(f, ok_msg="Error queue cleared")

    def refresh_now(self):
        self.run_bg(self._refresh_once)

    def _refresh_once(self):
        if not self.ctrl.is_connected():
            return
        try:
            tec_temp = self.ctrl.tec_temp()
        except Exception:
            tec_temp = None
        try:
            tec_state = self.ctrl.tec_state()
        except Exception:
            tec_state = None
        try:
            ld_meas = self.ctrl.ld_meas_current_a()
        except Exception:
            ld_meas = None
        try:
            ld_state = self.ctrl.ld_state()
        except Exception:
            ld_state = None
        try:
            err = self.ctrl.get_error()
        except Exception:
            err = "--"

        def update():
            self.tec_temp_var.set("--" if tec_temp is None else f"{tec_temp:.3f} °C")
            self.tec_state_var.set("ON" if tec_state == 1 else "OFF")
            self.ld_meas_mA_var.set("--" if ld_meas is None else f"{ld_meas * 1000:.4f}")
            self.ld_state_var.set("ON" if ld_state == 1 else "OFF")
            self.err_var.set(err)
        self.after(0, update)

    def start_polling(self):
        if self.polling:
            return
        self.polling = True
        self._poll_loop()

    def _poll_loop(self):
        if not self.polling:
            return
        if self.ctrl.is_connected():
            self.run_bg(self._refresh_once)
        self.after(1000, self._poll_loop)

    def run_sequence(self):
        self.stop_flag = False

        if self.sequence_thread and self.sequence_thread.is_alive():
            messagebox.showwarning("Busy", "A sequence is already running.")
            return
        if not self.ctrl.is_connected():
            messagebox.showwarning("Not connected", "Connect to the instrument first.")
            return

        peak_a = self.seq_peak_var.get() / 1000.0
        freq = self.seq_freq_var.get()
        cycles = self.seq_cycles_var.get()
        duty = self.seq_duty_var.get()

        if freq <= 0 or cycles <= 0 or not (0 < duty < 1):
            messagebox.showwarning("Invalid input", "Check frequency, cycles, and duty.")
            return

        def worker():
            try:
                self.ctrl.ld_on()
                time.sleep(0.2)
                self.ctrl.ld_set_current_a(0.0)
                time.sleep(0.1)
                period = 1.0 / freq
                t_on = period * duty
                t_off = period - t_on
                

                for i in range(cycles):
                    if self.stop_flag:
                        break

                    self.after(0, lambda i=i: self.set_status(f"Sequence running: cycle {i+1}/{cycles}"))
                    self.ctrl.ld_set_current_a(peak_a)

                    t = 0
                    while t < t_on:
                        if self.stop_flag:
                            break
                        time.sleep(0.02)
                        t += 0.02

                    try:
                        meas = self.ctrl.ld_meas_current_a() * 1000
                    except Exception:
                        meas = ""

                    

                    self.ctrl.ld_set_current_a(0.0)

                    t = 0
                    while t < t_off:
                        if self.stop_flag:
                            break
                        time.sleep(0.02)
                        t += 0.02

                self.ctrl.ld_set_current_a(0.0)

                if self.stop_flag:
                    self.after(0, lambda: self.set_status("Sequence stopped"))
                else:
                    self.after(0, lambda: self.set_status("Sequence finished"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Sequence error", str(e)))
                self.after(0, lambda: self.set_status("Sequence failed"))

        self.sequence_thread = threading.Thread(target=worker, daemon=True)
        self.sequence_thread.start()

    def run_sweep_sequence(self):
        self.stop_flag = False

        if self.sequence_thread and self.sequence_thread.is_alive():
            messagebox.showwarning("Busy", "A sequence is already running.")
            return
        if not self.ctrl.is_connected():
            messagebox.showwarning("Not connected", "Connect to the instrument first.")
            return

        def worker():
            try:
                self.ctrl.ld_on()
                levels_mA = [80, 70, 60, 50, 40, 30, 20, 10]
                on_time = 1.0
                off_time = 1.0
               
                for i, level in enumerate(levels_mA):
                    if self.stop_flag:
                        break

                    self.after(0, lambda i=i, level=level: self.set_status(f"Sweep step {i+1}: {level} mA"))
                    self.ctrl.ld_set_current_a(level / 1000.0)
                    time.sleep(on_time)

                    try:
                        meas = self.ctrl.ld_meas_current_a() * 1000
                    except Exception:
                        meas = ""

                  

                    self.ctrl.ld_set_current_a(0.0)
                    time.sleep(off_time)

                self.ctrl.ld_set_current_a(0.0)

                if self.stop_flag:
                    self.after(0, lambda: self.set_status("Sweep stopped"))
                else:
                    self.after(0, lambda: self.set_status("Sweep finished"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Sweep error", str(e)))
                self.after(0, lambda: self.set_status("Sweep failed"))

        self.sequence_thread = threading.Thread(target=worker, daemon=True)
        self.sequence_thread.start()

    def run_ppf_sequence(self):
        self.stop_flag = False

        if self.sequence_thread and self.sequence_thread.is_alive():
            messagebox.showwarning("Busy", "A sequence is already running.")
            return
        if not self.ctrl.is_connected():
            messagebox.showwarning("Not connected", "Connect to the instrument first.")
            return

        def worker():
            try:
                self.ctrl.ld_on()
                peak_mA = 80
                pulse_width = 0.2
                delays = [0.1, 0.2, 0.5, 1.0, 2.0]
              
                for i, delay in enumerate(delays):
                    if self.stop_flag:
                        break

                    self.after(0, lambda i=i, delay=delay: self.set_status(f"PPF step {i+1}: Δt={delay}s"))

                    self.ctrl.ld_set_current_a(peak_mA / 1000.0)
                    time.sleep(pulse_width)
                    self.ctrl.ld_set_current_a(0.0)

                    try:
                        a1 = self.ctrl.ld_meas_current_a() * 1000
                    except Exception:
                        a1 = ""

                    time.sleep(delay)

                    self.ctrl.ld_set_current_a(peak_mA / 1000.0)
                    time.sleep(pulse_width)
                    self.ctrl.ld_set_current_a(0.0)

                    try:
                        a2 = self.ctrl.ld_meas_current_a() * 1000
                    except Exception:
                        a2 = ""

                  

                    time.sleep(1.0)

                self.ctrl.ld_set_current_a(0.0)

                if self.stop_flag:
                    self.after(0, lambda: self.set_status("PPF stopped"))
                else:
                    self.after(0, lambda: self.set_status("PPF finished"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("PPF error", str(e)))
                self.after(0, lambda: self.set_status("PPF failed"))

        self.sequence_thread = threading.Thread(target=worker, daemon=True)
        self.sequence_thread.start()

    def run_spike_train(self):
        self.stop_flag = False

        if self.sequence_thread and self.sequence_thread.is_alive():
            messagebox.showwarning("Busy", "A sequence is already running.")
            return
        if not self.ctrl.is_connected():
            messagebox.showwarning("Not connected", "Connect to the instrument first.")
            return

        def worker():
            try:
                self.ctrl.ld_on()
                peak_mA = 80
                freq = 1.0
                cycles = 20
                duty = 0.5
              

                period = 1.0 / freq
                t_on = period * duty
                t_off = period - t_on

                for i in range(cycles):
                    if self.stop_flag:
                        break

                    self.after(0, lambda i=i: self.set_status(f"Spike {i+1}/{cycles}"))
                    self.ctrl.ld_set_current_a(peak_mA / 1000.0)
                    time.sleep(t_on)

                    try:
                        meas = self.ctrl.ld_meas_current_a() * 1000
                    except Exception:
                        meas = ""


                    self.ctrl.ld_set_current_a(0.0)
                    time.sleep(t_off)

                self.ctrl.ld_set_current_a(0.0)

                if self.stop_flag:
                    self.after(0, lambda: self.set_status("Spike train stopped"))
                else:
                    self.after(0, lambda: self.set_status("Spike train finished"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Spike train error", str(e)))
                self.after(0, lambda: self.set_status("Spike train failed"))

        self.sequence_thread = threading.Thread(target=worker, daemon=True)
        self.sequence_thread.start()

    def run_time_sequence(self):
        self.stop_flag = False

        if self.sequence_thread and self.sequence_thread.is_alive():
            messagebox.showwarning("Busy", "A sequence is already running.")
            return
        if not self.ctrl.is_connected():
            messagebox.showwarning("Not connected", "Connect first.")
            return

        peak_a = self.seq_peak_var.get() / 1000.0
        cycles = self.seq_cycles_var.get()
        t_on = self.seq_on_time_var.get()
        t_off = self.seq_off_time_var.get()

        if cycles <= 0 or t_on <= 0 or t_off < 0:
            messagebox.showwarning("Invalid input", "Check time and cycles.")
            return

        def worker():
            try:
                self.ctrl.ld_on()
                time.sleep(0.2)
                self.ctrl.ld_set_current_a(0.0)

             

                for i in range(cycles):
                    if self.stop_flag:
                        break

                    self.after(0, lambda i=i: self.set_status(f"Time Seq: {i+1}/{cycles}"))

                    # ON
                    self.ctrl.ld_set_current_a(peak_a)
                    time.sleep(t_on)

                    try:
                        meas = self.ctrl.ld_meas_current_a() * 1000
                    except:
                        meas = ""

                

                    # OFF
                    self.ctrl.ld_set_current_a(0.0)
                    time.sleep(t_off)

                self.ctrl.ld_set_current_a(0.0)

                if self.stop_flag:
                    self.after(0, lambda: self.set_status("Time sequence stopped"))
                else:
                    self.after(0, lambda: self.set_status("Time sequence finished"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
                self.after(0, lambda: self.set_status("Failed"))

        self.sequence_thread = threading.Thread(target=worker, daemon=True)
        self.sequence_thread.start()

    def stop_sequence(self):
        self.stop_flag = True
        try:
            self.ctrl.ld_set_current_a(0.0)
        except Exception:
            pass
        self.set_status("Stopping sequence...")
    
    def connect_ad2(self):
        try:
            msg = self.ad2.connect()
            self.set_status(msg)
        except Exception as e:
            messagebox.showerror("AD2 Error", str(e))

    def run_ad2_hardware_wave(self):
        target_mA = self.ad2_current_mA_var.get()
        freq = self.ad2_freq_var.get()
        duty = self.ad2_duty_var.get()
        cycles = self.ad2_cycles_var.get()

        if target_mA < 0 or target_mA > 80:
            messagebox.showwarning("Invalid current", "Target current should be 0–80 mA.")
            return
        if freq <= 0 or cycles <= 0 or not (0 < duty < 1):
            messagebox.showwarning("Invalid input", "Check frequency, cycles, and duty.")
            return

        coeff = 150.0
        V = target_mA / coeff

        try:
            node = c_int(0)

            # Build custom waveform:
            # 修改點 1: 改為 1.0 = ON, 0.0 = OFF (不再使用 -1.0)
            points_per_cycle = 100
            wave = []

            on_points = int(points_per_cycle * duty)
            off_points = points_per_cycle - on_points

            for _ in range(cycles):
                wave.extend([1.0] * on_points)
                wave.extend([0.0] * off_points)

            # 加入最後一段 OFF 確保結束時平滑
            wave.extend([0.0] * points_per_cycle)

            data = (c_double * len(wave))(*wave)

            # Enable W1
            self.ad2.dwf.FDwfAnalogOutNodeEnableSet(
                self.ad2.hdwf, self.ad2.channel, node, c_bool(True)
            )

            # Custom waveform function (30 = funcCustom)
            self.ad2.dwf.FDwfAnalogOutNodeFunctionSet(
                self.ad2.hdwf, self.ad2.channel, node, c_int(30)
            )

            # Load custom data
            self.ad2.dwf.FDwfAnalogOutNodeDataSet(
                self.ad2.hdwf, self.ad2.channel, node, data, c_int(len(wave))
            )

            # Frequency of the whole waveform
            waveform_freq = freq / (cycles + 1)
            self.ad2.dwf.FDwfAnalogOutNodeFrequencySet(
                self.ad2.hdwf, self.ad2.channel, node, c_double(waveform_freq)
            )

            # 修改點 2: 將 Amplitude 設為 V，Offset 設為 0.0
            self.ad2.dwf.FDwfAnalogOutNodeAmplitudeSet(
                self.ad2.hdwf, self.ad2.channel, node, c_double(V)
            )
            self.ad2.dwf.FDwfAnalogOutNodeOffsetSet(
                self.ad2.hdwf, self.ad2.channel, node, c_double(0.0)
            )

            # 修改點 3: 強制 AD2 結束時停留在 Offset 電壓 (0 = Disable, 1 = Offset, 2 = Initial)
            # 設定為 1，波形跑完就會穩穩地停在 Offset (也就是上面設定的 0.0 V)
            self.ad2.dwf.FDwfAnalogOutIdleSet(
                self.ad2.hdwf, self.ad2.channel, c_int(1)
            )

            total_duration = (cycles + 1) / freq

            # Hardware run duration
            self.ad2.dwf.FDwfAnalogOutRunSet(
                self.ad2.hdwf,
                self.ad2.channel,
                c_double(total_duration)
            )

            # Play once
            self.ad2.dwf.FDwfAnalogOutRepeatSet(
                self.ad2.hdwf,
                self.ad2.channel,
                c_int(1)
            )

            # Start
            self.ad2.dwf.FDwfAnalogOutConfigure(
                self.ad2.hdwf,
                self.ad2.channel,
                c_bool(True)
            )

            self.set_status(
                f"AD2 custom pulse: {cycles} cycles, {freq} Hz, 0→{target_mA:.1f} mA, ends at 0"
            )
            
            # 保留原本的 Python 安全重置 (作為保險，但因為有 IdleSet，不會再產生時間差突波)
            threading.Thread(
                target=self._force_ad2_zero_after,
                args=(total_duration,),
                daemon=True
            ).start()

        except Exception as e:
            messagebox.showerror("AD2 Error", str(e))
            
    def _force_ad2_zero_after(self, total_duration):
        time.sleep(total_duration + 0.05)

        try:
            self.ad2.set_voltage(0.0)
            self.after(0, lambda: self.set_status("AD2 finished, forced to 0 V"))
        except Exception as e:
            self.after(0, lambda e=e: self.set_status(f"AD2 zero error: {e}"))


        

    def stop_ad2(self):
        self.stop_flag = True
        try:
            self.ad2.set_voltage(0.0)
        except Exception:
            pass
        self.set_status("AD2 stopped, output set to 0 V")

    def on_close(self):
        self.polling = False
        try:
            self.ad2.close()
        except Exception:
            pass
        self.disconnect()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()