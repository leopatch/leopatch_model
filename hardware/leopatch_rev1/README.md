# LeoPatch Rev 1 (KiCad 9)

The bare-minimum board for LeoPatch: the nRF54LM20 DK (PCA10184 v0.7.0) reduced to the parts the patch
needs, plus an AD8232 ECG front end, a LiPo battery and a 2.7 V supply. The reasoning is in
[../LeoPatch_Rev1_PCB_Plan.pdf](../LeoPatch_Rev1_PCB_Plan.pdf).

## What's on the board

| Block | Parts |
|---|---|
| Radio core (copied from the DK) | U1 nRF54LM20B, crystals X1/X2, DC/DC and decoupling, antenna tuning, test connector J1, PCB antenna |
| Power | U3 nPM1300 charger and 2.7 V supply, J10 LiPo connector, RT1 battery thermistor |
| USB-C | J3 with ESD protection D1 and choke L8 (charging and USB data) |
| Storage | U4 8 MB flash |
| User interface | LD1–LD3 green/amber/red status LEDs, SW1 record/upload button |
| Programming | P11 SWD header (connect to the DK's Debug OUT) |
| ECG | U20 AD8232 (datasheet Fig. 66), J11 electrode connector: 1 LA, 2 RA, 3 RL |
| Bring-up test points | VBAT, VSYS, VDD_NRF, ECG_OUT, GND, UART TX/RX |

Removed from the DK:
- the debugger and its USB port
- the switches and level shifters
- all pin headers
- the NFC connector
- the extra LEDs and buttons
- the reset button (the SWD header can reset the chip)
- the DK's test points

## Files

| File | What it is |
|---|---|
| `leopatch_rev1.kicad_pro` | Open this in KiCad |
| `leopatch_rev1.kicad_sch` + 5 sheets | Root sheet, plus `radio`, `power`, `usb`, `io` and `ecg` sheets |
| `leopatch_rev1.kicad_pcb` | The board, already updated to match the schematic |
| `libraries/leopatch.kicad_sym` | Symbols: nRF54LM20B, nPM1300, AD8232, MX25R6435F, USB-C, ESD, choke, RF connector, MOSFET |
| `libraries/leopatch_dk.pretty` | The DK's own footprints, copied from its board |
| `libraries/leopatch.pretty` | AD8232 LFCSP-20 (CP-20-10) and JST PH connectors |
| `reference/` | The unmodified DK board converted to KiCad, for comparison |

The libraries are registered in this folder's `sym-lib-table` and `fp-lib-table`, so the project opens
the same on any Mac with KiCad 9.

## What has been checked

- **Schematic vs. design:** every pin (412) connects to the intended net, checked against KiCad's
  exported netlist.
- **Electrical rules check:** 0 errors, 0 warnings.
- **Schematic vs. PCB** (KiCad's schematic parity check): 0 differences. Every part is on the board,
  with the right footprint, value and nets.
- **Routing:** kept parts keep the DK's routing between them. Routing that only went to removed parts
  was deleted.
- **Design rules:** set to the smallest features Nordic's layout uses. Those are 0.1 mm clearance,
  0.2 mm microvias with 0.1 mm drills, and 0.05 mm annular rings, and the DK's 8-layer filled-via
  stack-up supports them.

## Next steps in the PCB Editor

1. **Place the new parts** sitting below the board: J11 (electrodes), J10 (battery), U20 and its
   R2xx/C2xx parts, RT1, C101, R101/R102 and the test points. Put the ECG section far from the antenna
   (right edge) and from the nPM1300's inductors L6/L7.
2. **Route the 110 unrouted connections.** The ratsnest lines show them. Most are the new parts. The
   rest are connections that went through removed DK parts:
   - flash U4 straight to P2.00–P2.05
   - crystal X2 to XL1/XL2
   - nPM1300 I2C (SDA P1.12, SCL P1.13), GPIO1 and GPIO3 to the nRF54
   - USB CC1/CC2 and VBUS to the nPM1300
3. **Shrink the board outline** if you like. Keep the antenna corner, its copper-free area and the
   ground around it as they are.
4. **Leave the radio section alone:** U1 and its capacitors, X1, X2, L1, L5, FB1, FB2, C6–C8, C14,
   L2–L4, C3, C12, C13, J1, C76 and the antenna copper.
5. **Run the DRC.** Items that came with the DK file itself:
   - 3 tiny Edge.Cuts segments (they go away when you redraw the outline)
   - USB vias inside a keepout
   - the USB shield copper
   - "footprint doesn't match library" warnings, which are cosmetic

After editing the schematic, use **Tools → Update PCB from Schematic** as normal. Footprints are already
linked to their symbols.

## Design notes

- **2.7 V supply:** R17 = 330 kΩ sets the nPM1300's VOUT1 start-up voltage (250–500 kΩ = 2.7 V). The
  AD8232 needs at least 2.0 V.
- **ECG filter:** C204 = 10 nF and C205 = 1.5 nF give the datasheet's 40 Hz low-pass. 3.3 nF and
  470 pF move it to about 128 Hz, closer to the model's training data. Try both.
- **Pin map:**
  - LED0, LED1, LED2 on P1.22, P1.25, P1.27; button on P1.26
  - flash on P2.00–P2.05
  - ECG OUT on P1.03/AIN7; SDN, LO+, LO− on P1.11, P1.14, P1.15
  - PMIC SDA, SCL on P1.12, P1.13; LED power on P1.10; PMIC interrupt on P1.24. I2C clocks must use
    the chip's clock pins (datasheet table 79); P1's clock pins are P1.03, P1.04, P1.07, P1.13, P1.14,
    P1.17, P1.18, P1.23 and P1.24
  - UART TX, RX on P0.06, P0.07
- **Net names:** these are global labels, so the same name on any sheet is the same net. `#FLG` symbols are
  KiCad power flags for the rules check, not parts.
