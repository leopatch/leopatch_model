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
                return np.array(rows, dtype=float).reshape(-1, 2)
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
            mv, off = data[:, 0], data[:, 1] > 0
            name = time.strftime("ecg_%Y%m%d_%H%M%S.csv")
            np.savetxt(name, data, delimiter=",", header="mv,lead_off", comments="", fmt="%g")

            t = np.arange(len(mv)) / FS
            fig, ax = plt.subplots(figsize=(12, 4))
            ax.plot(t, mv, lw=0.8)
            ax.fill_between(t, mv.min(), mv.max(), where=off, color="red", alpha=0.15,
                            label="lead off")
            ax.set(xlabel="time (s)", ylabel="AD8232 output (mV)",
                   title=f"{name}: {len(mv)} samples, swing {mv.max() - mv.min():.0f} mV")
            if off.any():
                ax.legend(loc="upper right")
            fig.tight_layout()
            print(f"saved {name}; close the plot window to record again")
            plt.show()


if __name__ == "__main__":
    main()
