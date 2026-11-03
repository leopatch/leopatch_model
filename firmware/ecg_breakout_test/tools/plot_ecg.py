"""Plot recordings from the ecg_breakout_test firmware.

Run it, then press Button 0 on the DK. Each 5 s recording is plotted and saved as a CSV.
Ctrl+C to quit.

usage: python plot_ecg.py [serial port]
The port defaults to the DK's second virtual serial port (the one ending in 3), which is where the
firmware prints.
"""
import glob
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import serial

FS = 500


def default_port():
    ports = sorted(glob.glob("/dev/tty.usbmodem*"))
    if not ports:
        sys.exit("No DK found: is the USB cable in the debugger port (J4)?")
    return ports[-1]


def read_recording(s):
    rows = []
    while True:
        line = s.readline().decode(errors="ignore").strip()
        if not line:
            continue
        if line.startswith("#"):
            print(line)
            if line.startswith("# start"):
                rows = []
            elif line.startswith("# done"):
                return np.array([r for r in rows if len(r) == 3], dtype=float).reshape(-1, 3)
        elif "," in line and rows is not None:
            try:
                rows.append([float(v) for v in line.split(",")])
            except ValueError:
                pass


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else default_port()
    print(f"Listening on {port}. Press Button 0 on the DK to record.")
    with serial.Serial(port, 115200, timeout=1) as s:
        while True:
            data = read_recording(s)
            if len(data) == 0:
                continue
            raw, mv, code = data[:, 0], data[:, 1], data[:, 2].astype(int)
            off = code > 0
            print(f"LO+ off in {np.mean((code & 1) > 0):.0%} of samples, LO- off in {np.mean((code & 2) > 0):.0%}")
            hum = raw - mv
            print(f"hum removed: {np.percentile(hum, 99) - np.percentile(hum, 1):.0f} mV peak to peak")
            name = time.strftime("ecg_%Y%m%d_%H%M%S.csv")
            np.savetxt(name, data, delimiter=",", header="raw_mv,filtered_mv,lead_off", comments="",
                       fmt="%g")

            t = np.arange(len(mv)) / FS
            fig, (ax_raw, ax) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
            ax_raw.plot(t, raw, lw=0.6, color="0.5")
            ax_raw.set(ylabel="raw (mV)", title=f"{name}: raw from the AD8232")
            ax.plot(t, mv, lw=0.9)
            ax.fill_between(t, mv.min(), mv.max(), where=off, color="red", alpha=0.15,
                            label="lead off")
            ax.set(xlabel="time (s)", ylabel="filtered (mV)",
                   title=f"60/120/180 Hz hum removed on the board, swing {mv.max() - mv.min():.0f} mV")
            if off.any():
                ax.legend(loc="upper right")
            fig.tight_layout()
            print(f"saved {name}; close the plot window to record again")
            plt.show()


if __name__ == "__main__":
    main()
