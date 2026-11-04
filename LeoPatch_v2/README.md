# LeoPatch v2 – PCB (KiCad 9)

Newborn CCHD ECG screening board. 4-layer, 70 × 45 mm.

- **MCU:** Fanstel BM20BC module (nRF54LM20B + Axon NPU, BLE, chip antenna at the top edge with a copper keep-out on all layers)
- **ECG front end:** AD8232 (SparkFun SEN-12650 circuit), 3-lead cable on a 3.5 mm TRS jack (T = RL, R = LA, S = RA) or the J202 header
- **Power:** 4×AA → on/off → BAT54J → MCP1703A 3.3 V LDO; USB-C 5 V also feeds the LDO through D102
- **USB-C (new in v2):** USB 2.0 device to the nRF54LM20B (firmware updates after the bootloader is flashed, data export, 5 V power). 5.1 k CC pull-downs, USBLC6-2SC6 ESD
- **UI:** PASS / CHECK / FAIL LEDs (green / yellow / red), EXPORT button
- **Programming:** first flash (MCUboot) through J301, the 10-pin SWD header, from the nRF54LM20 DK "Debug out"; after that, update over USB-C or BLE

> Safety: do not connect USB to a mains-powered computer while electrodes are on a patient.

## Stackup
F.Cu signals + GND pour · In1 solid GND · In2 solid +3V3 · B.Cu signals + GND pour.
Tracks 0.2 mm, clearance 0.15 mm, vias 0.45/0.2 mm (JLC standard 4-layer).

## Firmware pin map (BM20BC pad → GPIO → net)
| Pad | GPIO | Net |
|---|---|---|
| K8 | P1.06 / AIN4 | ECG_OUT |
| K9 | P1.31 / AIN1 | VBAT_SENSE (VBAT × 0.248) |
| C9 | P3.07 | ECG_LO+ |
| D9 | P0.05 | ECG_LO- |
| E9 | P1.16 | ECG_SDN (10 k pull-up) |
| F9 / G9 / H9 | P1.18 / P1.19 / P1.09 | LED green / yellow / red (active high) |
| J9 | P1.26 | BTN_EXPORT (to GND, use internal pull-up) |
| G6 / G7 / H7 | USB D- / D+ / VBUS | USB-C |
| K3 / J3 / G2 | SWDCLK / SWDIO / RESET | J301 |

## Folders
- `fab/` – Gerbers + drill (`LeoPatch_v2_gerbers.zip`), BOM, pick-and-place
- `docs/` – schematic PDF, 3D and top renders
- `layout/` – scripts that built the board: `place.py` (KiCad python: place parts from `placement.json`), `router.py` (grid router → `routes.json`), `apply_routes.py` (tracks, planes, antenna keep-out, zone fill)
- `3d/` – Fanstel BM20BC STEP model

## Status
DRC: 0 errors, 0 unconnected, schematic parity clean. Remaining warnings: J201 / SW101 silkscreen past the board edge (intentional overhang) and a KiCad library-copy notice on J102.
