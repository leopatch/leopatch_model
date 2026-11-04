"""Receive a recording from the LeoPatch board over Bluetooth.

Run it, then press Button 1 on the board (after a Button 0 recording). The board sends the result
and the recording; this runs the lead I model on it (score_lead1.py), saves everything as
ble_<date>_<time>.csv and plots the recording.

usage: python ble_receive.py           receive one recording, show the plot, exit
       python ble_receive.py --keep    keep listening; save each plot as a .png (Ctrl+C to stop)
On the first run, macOS asks to allow Bluetooth for the terminal app: allow it.
"""
import asyncio
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
from bleak import BleakClient, BleakScanner

from score_lead1 import p_male, verdict

NAME = "LeoPatch"
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # board -> receiver notifications
FS = 500


async def receive(timeout=60):
    print(f"Looking for {NAME}: press Button 1 on the board ...")
    dev = await BleakScanner.find_device_by_name(NAME, timeout=timeout)
    if dev is None:
        return None
    text = []
    done = asyncio.Event()

    def on_data(_, data):
        text.append(data.decode(errors="ignore"))
        if "# end" in text[-1]:
            done.set()

    async with BleakClient(dev) as client:
        print("Connected, receiving ...")
        await client.start_notify(NUS_TX, on_data)
        await asyncio.wait_for(done.wait(), timeout=30)
    return "".join(text)


def save(text, show):
    lines = text.splitlines()
    result = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("# result:")), "?")
    mv = np.array([float(l) for l in lines if l and not l.startswith("#")])
    name = time.strftime("ble_%Y%m%d_%H%M%S.csv")
    laptop = verdict(p_male(mv))
    with open(name, "w") as f:
        f.write(f"# result: {result}\n# laptop: {laptop}\nfiltered_mv\n")
        f.writelines(f"{v:g}\n" for v in mv)
    print(f"Board: {result}")
    print(f"Laptop: {laptop}")
    print(f"Received {len(mv)} samples, saved {name}")

    t = np.arange(len(mv)) / FS
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(t, mv, lw=0.9)
    ax.set(xlabel="time (s)", ylabel="filtered (mV)", title=f"{name}: {laptop}")
    fig.tight_layout()
    if show:
        plt.show()
    else:
        fig.savefig(name.replace(".csv", ".png"), dpi=120)
        plt.close(fig)


def main():
    if "--keep" not in sys.argv:
        text = asyncio.run(receive())
        if text is None:
            raise SystemExit(f"{NAME} not found. Did LED2 blink after pressing Button 1?")
        save(text, show=True)
        return
    print("Listening until Ctrl+C.")
    try:
        while True:
            try:
                text = asyncio.run(receive(timeout=3600))
            except Exception as e:  # dropped connection etc.: keep listening
                print(f"Receive failed ({e}), still listening")
                continue
            if text:
                save(text, show=False)
                time.sleep(3)  # let the board finish disconnecting before scanning again
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
