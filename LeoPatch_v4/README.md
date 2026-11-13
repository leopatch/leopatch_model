# LeoPatch v4 – PCB (KiCad 9)

Newborn CCHD ECG screening board with **two ECG front ends side by side**, so they can be compared on the same hardware: the MAX30003 (digital, SPI) from v3 and the AD8232 (analog, SparkFun circuit) from v2. Each chip has its **own electrode jack**. Plug the lead cable into the jack of the chip you want to test. Do not put two sets of electrodes from both jacks on the same baby at once: the AD8232 drives RL, and the two input circuits would load each other.

4-layer, **70 × 71 mm** (v3 was 70 × 45; the board grew 26 mm at the bottom to make room for the AD8232 block and its jack). Top edge has the 20 × 6.6 mm cut-out under the module's antenna.

- **MCU:** Fanstel BM20BC module (nRF54LM20B + Axon NPU, BLE, 32 MHz and 32.768 kHz crystals built in). Its antenna hangs over the cut-out in the top edge. Keep the battery pack, cables and other metal away from that edge (Fanstel: 30 mm for best range)
- **ECG front end A – MAX30003 (U201, sheet "ECG front end"):** two-electrode lead I (ECGP = LA, ECGN = RA), 1.8 V from U202 (MCP1700T-1802E/TT in v4: the MCP1703AT-1802E/CB had 3 pcs at LCSC; same SOT-23 pinout), 32.768 kHz clock from X201, SPI to the module. Jack **J201 on the left edge** (plug goes in from the left), backup solder header J202. Silkscreen "MAX30003"
  - Input network matches Analog Devices' MAX30003WING2 evaluation kit (checked against it and the MAX30003 datasheet Rev 3): R201 / R202 49.9 kΩ pulse-proof 1206 (eval kit R4/R5 49.9k; Vishay CRCW…HP), C201 1 nF C0G across ECGP–ECGN (eval kit C10), C213 / C214 10 pF C0G from each input to GND (eval kit C8/C11), R208 499 kΩ from VCM to the RL electrode (eval kit R6: biases the baby at the chip's mid-voltage)
  - C202 (CAPP–CAPN) is 1 µF X7R: 0.5 Hz analog high-pass (datasheet default and eval kit C9), settles in ~1–2 s after the electrodes go on – fits the 2–5 s recordings
  - Firmware must close the input switches (clear OPENP / OPENN in CNFG_EMUX, they power up open). Internal lead bias (EN_RBIAS) is optional now that R208 drives RL from VCM; try with and without. SPI mode 0 or 3, ≤ 12 MHz. The part is rated 0–70 °C
- **ECG front end B – AD8232 (U601, sheet "ECG AD8232"):** the v2 circuit (SparkFun SEN-12650 / AD8232 datasheet Fig. 66 with a wider filter): band 0.5 Hz – ~145 Hz, gain ~200, clips at about ±7.8 mV at the electrodes. Jack **J601 on the bottom edge**, backup header J602, test pad TP601 ("ECG") on the op-amp output. Silkscreen "AD8232". Checked against the AD8232 datasheet (Rev D) in v4: R603 / R604 are 360 kΩ (patient current < 10 µA even in a fault: R ≥ 3.3 V / 10 µA, p. 21 and 26; was 180 k), and the output goes OUT → R623 1 kΩ → ECG_OUT with C608 10 nF to GND (p. 26 Fig. 61: the slow op amp needs a charge reservoir for the nRF54 ADC). SDN is only pulled up (R615): the AD8232 is always on. The reference (REFIN, 10 M / 10 M / 100 nF) takes ~2.5 s to settle after power-up
- Both jacks: 3.5 mm TRS, Tip = RL, Ring = LA, Sleeve = RA (same cable for both). Headers: pin 1 RL, 2 LA, 3 RA
- **External flash:** GD25WQ64ESIGR 8 MB SPI/QSPI NOR (U2, C4) on P2.00–P2.05, same pins as the nRF54LM20 DK flash. R2 (100 k) pulls FLASH_CS high. **v4 fix:** this part number is the 208-mil SOP-8 (the S in ESIGR); v2/v3 had a 150-mil SOIC-8 footprint it would not fit. U2 now uses SOIC-8 5.3 × 5.3 mm
- **Power:** 4×AA → on/off → BAT54J → MCP1703A 3.3 V LDO; USB-C 5 V also feeds the LDO through D102. Alligator-clip pins J103 **VIN** (3.6–6 V after the diodes, bypasses the on/off switch), J104 **3V3** (to feed 3.3 V in from a bench supply, or to measure current across JP101, desolder R101 first: R101 0 Ω is in parallel with JP101 and links the regulator to the 3.3 V rail), J105 **GND**
- **USB-C:** USB 2.0 device to the nRF54LM20B (firmware updates after the bootloader is flashed, data export, 5 V power). D+/D- top layer only, length-matched
- **UI:** PASS / CHECK / FAIL LEDs (green / yellow / red), START and EXPORT buttons, small RESET button (SW303). R301 (green LED) is 100 Ω: a green InGaN LED needs ~3 V, so 1 k from a 3.3 V pin gave only ~0.2 mA
- **Status LEDs (v4):** D103 **PWR** (green, on whenever the 3.3 V rail is up, ~0.5 mA) next to the 3V3 pin; a **LEADS ON** panel bottom right with D201 (MAX30003) and D601 (AD8232), green, active high. Firmware lights D201 while the MAX30003 reports no lead-off (DCLOFFINT clear) and D601 while the AD8232's LO+ and LO- are both low. The jacks have no plug-detect contact, so "leads on" (both electrodes touching skin) is what can be shown. Heartbeat LEDs did not fit: these used the last module pins that can still be routed out
- **Mounting:** five M2 holes (2.2 mm, not plated): H1 (104.0, 124.5), H2 (125.5, 112.0), H3 (167.5, 120.0), H4 (166.0, 167.0), H5 (104.0, 147.5) mm in board coordinates; top-left corner is (100, 100), y grows downward. Use nylon screws if range matters
- **Test points** (bare top-side pads, not in the BOM, silk-labelled): TP1 GND, TP2 +3V3, TP601 "ECG" = AD8232 output before its RC filter; TP202–TP206 "CS SCK MOSI MISO INT" = MAX30003 SPI bus (logic analyzer), TP201 "FCLK" = 32 kHz clock from X201, TP207 "1V8" = U202 output (MAX30003 DVDD); TP602 "ADC" = ECG_OUT after R623/C608 (what the nRF54 ADC sees) with TP604 "GND" beside it for the scope ground; TP603 "REF" = AD8232 REFOUT (~1.65 V); TP101 "VSNS" = battery divider. No test points on ECGP/ECGN, INP/INN or chip-side LA/RA (high impedance: a pad adds leakage and pickup); inject test signals at J202 / J602. Schematic: layout/fix_v4_testpoints_sch.py
- **Programming:** first flash (MCUboot) through J301, the 10-pin SWD header, from the nRF54LM20 DK "Debug out"; after that, update over USB-C or BLE

> Safety: do not connect USB to a mains-powered computer while electrodes are on a patient.


## Audio jacks and 3D models
- **J201 / J601 are CUI (Same Sky) SJ-3523-SMT-TR**, KiCad stock footprint `Connector_Audio:Jack_3.5mm_CUI_SJ-3523-SMT_Horizontal`. The barrel is at the footprint's -y end, so J201 is at 90° (plug from the left edge) and J601 at 180° (plug from the bottom edge), barrel tip flush with the edge. **v2, v3 and v4 before 2026-11-13 had both jacks backwards** (barrel facing into the board, body hanging off the edge): a plug could not go in.
- 3D models are project-relative (`${KIPRJMOD}/3d/...`), set by `layout/set_3d_models.py` (run by `build_all.sh`). `3d/bm20bc.step` is in git. `3d/SJ-3523-SMT-TR.step` is **not** in git (`.gitignore`), because the SamacSys licence forbids redistributing it outside your organisation and this repo is public. To see the jacks in 3D, download the SJ-3523-SMT-TR library from samesky.com (or componentsearchengine.com), then copy `3D/SJ-3523-SMT-TR.stp` to `LeoPatch_v4/3d/SJ-3523-SMT-TR.step`. Without it the jacks just render as footprints; the gerbers are unaffected.

## Firmware pin map (BM20BC pad → GPIO → net)
| Pad | GPIO | Net |
|---|---|---|
| E9 | P1.16 | ECG_SCK (MAX30003 SCLK) |
| K8 | P1.06 | ECG_MOSI (MAX30003 SDI) |
| A8 | P1.02 | ECG_MISO (MAX30003 SDO) – P1.02 is also the NFC2 pin: configure the NFC pins as GPIOs in firmware |
| D9 | P0.05 | ECG_CS (MAX30003 CSB) |
| C9 | P3.07 | ECG_INT (MAX30003 INTB, active low, 100 k pull-up R205) |
| F7 | P1.29 / **AIN3** | ECG_OUT (AD8232 output through R623 1 k / C608 10 nF, analog) |
| D8 | P3.06 | ECG_LO+ (AD8232 lead-off) |
| E8 | P1.25 | ECG_LO- (AD8232 lead-off) |
| A7 | P3.03 | LED_MAX_LEADS (D201, MAX30003 LEADS ON, active high) |
| F8 | P1.17 | LED_AD_LEADS (D601, AD8232 LEADS ON, active high) |
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
- The AD8232 is always powered (SDN tied high); the MAX30003 can stay in its power-down state while you test the AD8232.
- Free module pads: only A5 (P0.00) and G8 (P1.08) are still unconnected, and with the current layout neither can be routed out without moving other tracks.

## Stackup
F.Cu signals + GND pour · In1 solid GND · In2 solid +3V3 · B.Cu signals + GND pour.
Tracks 0.2 mm (0.15 mm on every net that reaches the module, 0.3 mm on +1V8), clearance 0.15 mm, vias 0.45/0.3 mm (JLC standard "0.3mm/(0.4/0.45mm)" via option; set by layout/set_via_drill.py, order stackup JLC04161H-7628).
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
  - `LeoPatch_v4_BOM_detailed.csv` – the same parts for people, with datasheet links and sourcing notes
  - Parts with no LCSC stock (no LCSC number in the BOM): none now (see below) – use JLC Global Sourcing or buy them (DigiKey/Mouser) and consign. JP101 needs no jumper cap (R101 0 Ω already links the regulator to the 3.3 V rail). The through-hole headers (J101, J103–J105, J202, J602, JP101) can be left out of the order and hand-soldered
  - **U1, U201 and J201/J601 come through JLC Global Sourcing** (LCSC C55288626 BM20BC from DigiKey, C5354728 MAX30003CTI+T from Mouser, C4991872 SJ-3523-SMT-TR from DigiKey; 10–20 business days). Order 5 / 5 / 10 for 5 boards. Pin headers / JST are moved to their body centre and the 1xN headers turned 90° in the CPL for JLC; 0603 LEDs turned 180°.
  - **X201 is a Micro Crystal OV-7604-C7** (LCSC C5337982, in stock, 0.5 µA): it replaced the Epson SG-3030CM (Global Sourcing minimum 808 pcs). Same land pattern, but pin 1 = CLKOUT and pin 3 = CLKOE (the Epson has them the other way round); the schematic symbol and board nets follow the OV-7604 (`layout/fix_v4_x201_sch.py`). Do not fit an SG-3030CM on v4.
  - Check every IC's pin-1 dot in JLC's placement preview before paying (rotation conventions differ between JLC library parts); J301, U2, U101, U102, U202, SW303 have corrections applied
- `docs/` – schematic PDF and top render
- `layout/` – scripts. v4 is built by `build_all.sh` (KiCad closed): it starts from `v4_start.kicad_pcb` (the v3 board), then
  - `add_ad8232_sheet.py` – schematic (run once, already applied): the v2 AD8232 sheet as `LeoPatch_ECG_AD8232.kicad_sch` (parts 2xx → 6xx), the new sheet in the root, the four module pads on the MCU sheet
  - `build_v4_pcb.py` – rips up the v3 MAX30003 tracks, makes the board taller, sets pad nets from the netlist, moves J201 / H4, adds H5, copies the v2 AD8232 block with its tracks 26 mm lower
  - `dump_geom.py` → `route_new.py` → `apply_new_routes.py` – routes everything still unrouted around the existing copper (grid A* router, order in `route_order.json`) and deletes dangling copper; `plot_geom.py` draws the result for checking
  - `refill.py`, then DRC with schematic parity → `drc.json`, then `make_jlc_files.py` (BOM / CPL from `parts.csv`)
  - `parts.csv` – the chosen part for every reference (manufacturer, MPN, LCSC number, **datasheet link**); `set_part_fields.py` writes it into the schematic as Manufacturer / MPN / LCSC fields and the Datasheet field (click it in KiCad), also the U2 footprint, U202 / U101 / R301 values
  - `fix_v4_batch_sch.py` – the eval-kit / datasheet fixes and the status LEDs (schematic side)
  - `check_coupling.py` – analog / digital proximity and USB pair report
  - older v2 / v3 scripts are kept for reference

## Status
DRC (2026-11-12, after the coupling re-route and the flash footprint fix): **0 errors, 0 unconnected, schematic parity clean.** Remaining warnings: silkscreen past the board edge on parts that overhang it on purpose (J201, J601, SW101, U1) and a KiCad library-copy notice on J102. ERC: only library warnings and the VBUS power-flag warning carried over from v3.

The v3 board (LeoPatch_v3) is **not** fab-ready: its MAX30003 routing has 28 shorts and 13 unconnected nets (its README status line was copied from v2). v4 replaces all of that routing.
