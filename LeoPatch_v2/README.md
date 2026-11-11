# LeoPatch v2 – PCB (KiCad 9)

Newborn CCHD ECG screening board. 4-layer, 70 × 45 mm, with a 20 × 6.6 mm cut-out in the top edge under the module's antenna.

- **MCU:** Fanstel BM20BC module (nRF54LM20B + Axon NPU, BLE, 32 MHz and 32.768 kHz crystals built in). Its chip antenna hangs over a cut-out in the top edge, 5 mm wider than the module on each side, as the Fanstel datasheet recommends. Keep the battery pack, cables and other metal away from that edge (Fanstel: 30 mm for best range)
- **ECG front end:** AD8232 (SparkFun SEN-12650 circuit with a wider filter), 3-lead cable on a 3.5 mm TRS jack (T = RL, R = LA, S = RA) or the J202 header. Band 0.5 Hz – ~145 Hz, total gain ~200 (R208 1 M, C201 1 nF, C203 1.2 nF; use C0G capacitors), chosen for chest leads on newborns: it clips at about ±7.8 mV at the electrodes. Do any further scaling in firmware. Sample at 1 kHz or more (oversample and average if you can) and notch out mains hum in firmware
- **External flash:** GD25WQ64E 8 MB SPI/QSPI NOR (U2, C4) on P2.00–P2.05, same pins as the nRF54LM20 DK flash. R2 (100 k) pulls FLASH_CS high so the flash stays deselected while the MCU pins float
- **Power:** 4×AA → on/off → BAT54J → MCP1703A 3.3 V LDO; USB-C 5 V also feeds the LDO through D102. Three single pins spaced for alligator clips: J103 **VIN** goes to the regulator input after the battery and USB diodes, so an external 3.6–6 V supply can sit in parallel with them without back-feeding either (it bypasses the on/off switch); J104 **3V3** is the 3.3 V rail (to feed 3.3 V in from a bench supply, pull the JP101 jumper first); J105 **GND**
- **USB-C (new in v2):** USB 2.0 device to the nRF54LM20B (firmware updates after the bootloader is flashed, data export, 5 V power). 5.1 k CC pull-downs, USBLC6-2SC6 ESD. D+ / D- run on the top layer only (no vias), straight through the ESD chip, 0.27 mm wide outside the module (about 90 Ω as a pair) and length-matched (14.44 / 14.42 mm)
- **UI:** PASS / CHECK / FAIL LEDs (green / yellow / red), START button (begin a recording) and EXPORT button (send the stored data); small RESET button (SW303) below EXPORT
- **Mounting:** four M2 holes (2.2 mm, not plated) H1–H4 at (104.0, 124.5), (125.5, 112.0), (167.5, 120.0), (154.5, 142.0) mm in board coordinates; the board's top-left corner is (100, 100) and y grows downward. Use nylon screws if range matters
- **Test points:** TP1 GND, TP2 +3V3, TP3 ECG_OUT (1 mm pads next to the AD8232 output filter, labelled on the silkscreen)
- **Programming:** first flash (MCUboot) through J301, the 10-pin SWD header, from the nRF54LM20 DK "Debug out"; after that, update over USB-C or BLE

> Safety: do not connect USB to a mains-powered computer while electrodes are on a patient.

## Stackup
F.Cu signals + GND pour · In1 solid GND · In2 solid +3V3 · B.Cu signals + GND pour.
Tracks 0.2 mm (0.15 mm for the flash and USB escapes under the module), clearance 0.15 mm, vias 0.45/0.2 mm (JLC standard 4-layer, order stackup JLC04161H-7628).
Vias are tented and none sits inside a pad (only exception: the two ground vias in the AD8232 centre pad).
Under the module there are only 12 GND / +3V3 vias, between the pads, straight to the planes. Every signal leaves the module on the top layer through the lanes between pads and changes layer outside the module outline; the only bottom-layer tracks crossing under it are VBUS and VBAT_SENSE (both DC, behind the ground plane).

## Firmware pin map (BM20BC pad → GPIO → net)
| Pad | GPIO | Net |
|---|---|---|
| K8 | P1.06 / AIN4 | ECG_OUT |
| K9 | P1.31 / AIN1 | VBAT_SENSE (VBAT × 0.248) |
| C9 | P3.07 | ECG_LO+ |
| D9 | P0.05 | ECG_LO- |
| E9 | P1.16 | ECG_SDN (10 k pull-up) |
| F9 / G9 | P1.18 / P1.19 | LED green / yellow (active high) |
| K2 | P3.10 | LED red (active high) |
| H9 | P1.09 | BTN_START (to GND, use internal pull-up) |
| J9 | P1.26 | BTN_EXPORT (to GND, use internal pull-up) |
| G6 / G7 / H7 | USB D- / D+ / VBUS | USB-C |
| K3 / J3 / G2 | SWDCLK / SWDIO / RESET | J301 |
| B2 | P2.01 | FLASH_SCK |
| B6 | P2.05 | FLASH_CS |
| E2 | P2.02 | FLASH_IO0 (MOSI) |
| B5 | P2.04 | FLASH_IO1 (MISO) |
| B4 | P2.03 | FLASH_IO2 (WP#) – drive high in plain SPI mode |
| B3 | P2.00 | FLASH_IO3 (HOLD#) – drive high in plain SPI mode |

## Folders
- `fab/` – Gerbers + drill (`LeoPatch_v2_gerbers.zip`), BOM, pick-and-place
- `docs/` – schematic PDF, 3D and top renders
- `layout/` – scripts that built the board: `place.py` (KiCad python: place parts from `placement.json`), `router.py` (grid router → `routes.json`), `apply_routes.py` (tracks, planes, antenna keep-out, zone fill), then `add_flash_sch.py` / `add_flash_pcb.py` / `route_flash.py` (external flash), then the design-review rework: `add_pullup_testpoints_sch.py`, `add_power_headers_sch.py` `add_start_button_sch.py` and `add_reset_gain_sch.py` (R2, test points, power pins, START and RESET buttons, gain 200 in the schematic), `rework_review.py` (antenna cut-out, via-free matched USB, no signal vias under the module, R2 / test points / power pins / mounting holes / START and RESET buttons / gain 200 on the board), `move_vias_out_of_pads.py`, `refill.py`
- `3d/` – Fanstel BM20BC STEP model

## Status
DRC: 0 errors, 0 unconnected, schematic parity clean. Remaining warnings: J201 / SW101 / U1 silkscreen past the board edge (parts that overhang the edge or the antenna cut-out) and a KiCad library-copy notice on J102.
Module pad map and footprint (10.0 × 16.2 mm, 0.9 mm pitch, 0.4 mm pads) were checked against the Fanstel BM20C product specification v1.00 (Oct 2026).
