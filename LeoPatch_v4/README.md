# LeoPatch v4 – PCB (KiCad 9)

Newborn CCHD ECG screening board with **two ECG front ends side by side**, so they can be compared on the same hardware: the MAX30003 (digital, SPI) from v3 and the AD8232 (analog, SparkFun circuit) from v2. Each chip has its **own electrode jack**. Plug the lead cable into the jack of the chip you want to test. Do not put two sets of electrodes from both jacks on the same baby at once: the AD8232 drives RL, and the two input circuits would load each other.

4-layer, **70 × 71 mm** (v3 was 70 × 45; the board grew 26 mm at the bottom to make room for the AD8232 block and its jack). Top edge has the 20 × 6.6 mm cut-out under the module's antenna.

- **MCU:** Fanstel BM20BC module (nRF54LM20B + Axon NPU, BLE, 32 MHz and 32.768 kHz crystals built in). Its antenna hangs over the cut-out in the top edge. Keep the battery pack, cables and other metal away from that edge (Fanstel: 30 mm for best range)
- **ECG front end A – MAX30003 (U201, sheet "ECG front end"):** two-electrode lead I (ECGP = LA, ECGN = RA), 1.8 V from U202 (MCP1700T-1802E/TT in v4: the MCP1703AT-1802E/CB had 3 pcs at LCSC; same SOT-23 pinout), 32.768 kHz clock from X201, SPI to the module. Jack **J201 on the left edge** (plug goes in from the left), backup solder header J202. Silkscreen "MAX30003"
  - Input network checked against the MAX30003 datasheet (Rev 3, Figure 11) in v4: R201 / R202 1 kΩ are pulse-proof 1206 parts (Vishay CRCW…HP; the datasheet wants them energy-rated for 8 kV), then C201 10 nF C0G across ECGP–ECGN and C213 / C214 1 nF C0G from each input to GND, all on the chip side of the resistors (v3 had a single 1 nF across the electrode side)
  - C202 (CAPP–CAPN) is 10 µF: 0.035 Hz analog high-pass, time constant ≈ 4.5 s. For 2–5 s recordings either use 1 µF (datasheet default, 0.5 Hz, settles in ~1–2 s) or keep 10 µF and run manual fast recovery (MNGR_DYN) after lead-on before recording
  - Firmware must close the input switches (clear OPENP / OPENN in CNFG_EMUX, they power up open) and turn on internal lead bias (EN_RBIAS = 01, RBIASP = RBIASN = 1 in CNFG_GEN) – with two electrodes nothing else holds the inputs in their ±150 mV common-mode range. SPI mode 0 or 3, ≤ 12 MHz. The part is rated 0–70 °C
- **ECG front end B – AD8232 (U601, sheet "ECG AD8232"):** the v2 circuit unchanged (SparkFun SEN-12650 with a wider filter): band 0.5 Hz – ~145 Hz, gain ~200, clips at about ±7.8 mV at the electrodes. Analog output to the module's ADC. Jack **J601 on the bottom edge**, backup header J602, output test pad TP601 ("ECG"). Silkscreen "AD8232". SDN has a 10 k pull-up (R615), so the AD8232 is on unless firmware pulls SDN low
- Both jacks: 3.5 mm TRS, Tip = RL, Ring = LA, Sleeve = RA (same cable for both). Headers: pin 1 RL, 2 LA, 3 RA
- **External flash:** GD25WQ64ESIGR 8 MB SPI/QSPI NOR (U2, C4) on P2.00–P2.05, same pins as the nRF54LM20 DK flash. R2 (100 k) pulls FLASH_CS high. **v4 fix:** this part number is the 208-mil SOP-8 (the S in ESIGR); v2/v3 had a 150-mil SOIC-8 footprint it would not fit. U2 now uses SOIC-8 5.3 × 5.3 mm
- **Power:** 4×AA → on/off → BAT54J → MCP1703A 3.3 V LDO; USB-C 5 V also feeds the LDO through D102. Alligator-clip pins J103 **VIN** (3.6–6 V after the diodes, bypasses the on/off switch), J104 **3V3** (pull JP101 first to feed 3.3 V in), J105 **GND**
- **USB-C:** USB 2.0 device to the nRF54LM20B (firmware updates after the bootloader is flashed, data export, 5 V power). D+/D- top layer only, length-matched
- **UI:** PASS / CHECK / FAIL LEDs (green / yellow / red), START and EXPORT buttons, small RESET button (SW303). R301 (green LED) is 100 Ω in v4: a green InGaN LED needs ~3 V, so 1 k from a 3.3 V pin gave only ~0.2 mA
- **Mounting:** five M2 holes (2.2 mm, not plated): H1 (104.0, 124.5), H2 (125.5, 112.0), H3 (167.5, 120.0), H4 (166.0, 167.0), H5 (104.0, 147.5) mm in board coordinates; top-left corner is (100, 100), y grows downward. Use nylon screws if range matters
- **Test points:** TP1 GND, TP2 +3V3, TP601 AD8232 output
- **Programming:** first flash (MCUboot) through J301, the 10-pin SWD header, from the nRF54LM20 DK "Debug out"; after that, update over USB-C or BLE

> Safety: do not connect USB to a mains-powered computer while electrodes are on a patient.

## Firmware pin map (BM20BC pad → GPIO → net)
| Pad | GPIO | Net |
|---|---|---|
| E9 | P1.16 | ECG_SCK (MAX30003 SCLK) |
| K8 | P1.06 | ECG_MOSI (MAX30003 SDI) |
| A8 | P1.02 | ECG_MISO (MAX30003 SDO) – P1.02 is also the NFC2 pin: configure the NFC pins as GPIOs in firmware |
| D9 | P0.05 | ECG_CS (MAX30003 CSB) |
| C9 | P3.07 | ECG_INT (MAX30003 INTB, active low, 100 k pull-up R205) |
| F7 | P1.29 / **AIN3** | ECG_OUT (AD8232 output, analog) |
| D8 | P3.06 | ECG_LO+ (AD8232 lead-off) |
| E8 | P1.25 | ECG_LO- (AD8232 lead-off) |
| A7 | P3.03 | ECG_SDN (AD8232 shutdown, low = off; 10 k pull-up R615) |
| K9 | P1.31 / AIN1 | VBAT_SENSE (VBAT × 0.248) |
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

nRF54LM20 analog inputs (from Nordic's SDK, `nrfx_soc_defines.h`; the Fanstel datasheet only lists AIN numbers for the BM15 module): AIN0 P1.00, AIN1 P1.31, AIN2 P1.30, AIN3 P1.29, AIN4 P1.06, AIN5 P1.05, AIN6 P1.04, AIN7 P1.03. The DK firmware reads AIN6 (P1.04); on this board the AD8232 output is **AIN3**.

Firmware notes for comparing the two chips:
- Sample the AD8232 at 1 kHz or more and notch mains hum in firmware, as in v2. Its output runs next to the MAX30003 SPI lines for part of the way, so do not clock the MAX30003 SPI while you sample the AD8232 (read one chip at a time).
- When testing the MAX30003, you can pull SDN low to switch the AD8232 off (saves ~170 µA); when testing the AD8232, the MAX30003 can stay in its power-down state.

## Stackup
F.Cu signals + GND pour · In1 solid GND · In2 solid +3V3 · B.Cu signals + GND pour.
Tracks 0.2 mm (0.15 mm on every net that reaches the module, 0.3 mm on +1V8), clearance 0.15 mm, vias 0.45/0.2 mm (JLC standard 4-layer, order stackup JLC04161H-7628).
Vias are tented. None sits inside a pad except the ground vias in the exposed pads of the AD8232 and the MAX30003.
No vias and no new bottom-layer tracks under the module. Signals leave it on the top layer through the lanes between pads; the AD8232 lines leave through the lanes beside D9 / E9 / F9.

### Coupling check (`layout/check_coupling.py`, report in `layout/coupling_report.txt`)
Sensitive analog nets (ECG_OUT, all AD8232 nodes, MAX30003 inputs / references / +1V8, VBAT_SENSE) are kept at least 0.5 mm (edge to edge) from switching lines (MAX30003 SPI + INT, the 32 kHz FCLK, flash, USB, SWD) on the same layer; the router treats closer runs as expensive and routes in two passes so the early analog nets avoid where the digital lines go. F.Cu and B.Cu are shielded from each other by the two inner planes, so only same-layer neighbours count. What is left closer than 0.5 mm:
- ECG_OUT / ECG_SCK 1.9 mm at 0.25 mm – the module escape lanes (F7 sits next to E9), unavoidable; read one chip at a time anyway
- ECG_MOSI / VBAT_SENSE 1.1 mm at 0.46 mm on B.Cu at the module edge – VBAT_SENSE is a DC divider with 100 nF (C104); MOSI only toggles while configuring the MAX30003
- +1V8 / FCLK 0.1 mm at the MAX30003's neighbouring pins 13 / 14
Analog-to-analog neighbours inside each front end (e.g. LA next to RA, CAPP next to CAPN, the copied v2 AD8232 layout) are expected.
USB D+ / D-: top layer only, no vias, 16.02 / 15.92 mm, 0.27 mm wide, ~0.23 mm gap where coupled (~90 Ω differential on JLC04161H-7628).

## Folders
- `fab/` – Gerbers + drill (`LeoPatch_v4_gerbers.zip`, also unzipped in `gerbers/`) and the JLCPCB assembly files:
  - `LeoPatch_v4_JLC_BOM.csv` – Comment (part description + MPN), Designator, Footprint, LCSC Part #, Manufacturer, MPN, Quantity
  - `LeoPatch_v4_JLC_CPL.csv` – Designator, Mid X, Mid Y, Layer, Rotation (JLC rotation corrections applied, `layout/jlc_rotations.csv`)
  - `LeoPatch_v4_BOM_detailed.csv` – the same parts for people, with sourcing notes
  - Parts with no LCSC stock (no LCSC number in the BOM): **U1 BM20BC** (Fanstel, consign), **U201 MAX30003CTI+T**, **J201/J601 CUI SJ-3523-SMT-TR**, **X201 Epson SG-3030CM** – use JLC Global Sourcing or buy them (DigiKey/Mouser) and consign. JP101 needs a 2.54 mm jumper cap fitted by hand. The through-hole headers (J101, J103–J105, J202, J602, JP101) can be left out of the order and hand-soldered
  - Check every IC's pin-1 dot in JLC's placement preview before paying (rotation conventions differ between JLC library parts); J301, U2, U101, U102, U202, SW303 have corrections applied
- `docs/` – schematic PDF and top render
- `layout/` – scripts. v4 is built by `build_all.sh` (KiCad closed): it starts from `v4_start.kicad_pcb` (the v3 board), then
  - `add_ad8232_sheet.py` – schematic (run once, already applied): the v2 AD8232 sheet as `LeoPatch_ECG_AD8232.kicad_sch` (parts 2xx → 6xx), the new sheet in the root, the four module pads on the MCU sheet
  - `build_v4_pcb.py` – rips up the v3 MAX30003 tracks, makes the board taller, sets pad nets from the netlist, moves J201 / H4, adds H5, copies the v2 AD8232 block with its tracks 26 mm lower
  - `dump_geom.py` → `route_new.py` → `apply_new_routes.py` – routes everything still unrouted around the existing copper (grid A* router, order in `route_order.json`) and deletes dangling copper; `plot_geom.py` draws the result for checking
  - `refill.py`, then DRC with schematic parity → `drc.json`, then `make_jlc_files.py` (BOM / CPL from `parts.csv`)
  - `parts.csv` – the chosen part for every reference (manufacturer, MPN, LCSC number); `set_part_fields.py` writes it into the schematic as Manufacturer / MPN / LCSC fields (also the U2 footprint, U202 / U101 / R301 values)
  - `check_coupling.py` – analog / digital proximity and USB pair report
  - older v2 / v3 scripts are kept for reference

## Status
DRC (2026-11-12, after the coupling re-route and the flash footprint fix): **0 errors, 0 unconnected, schematic parity clean.** Remaining warnings: silkscreen past the board edge on parts that overhang it on purpose (J201, J601, SW101, U1) and a KiCad library-copy notice on J102. ERC: only library warnings and the VBUS power-flag warning carried over from v3.

The v3 board (LeoPatch_v3) is **not** fab-ready: its MAX30003 routing has 28 shorts and 13 unconnected nets (its README status line was copied from v2). v4 replaces all of that routing.
