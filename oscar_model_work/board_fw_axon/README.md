# board_fw_axon -- the minimized ECG sex model on the Axon NPU (nRF54LM20B DK)

**Status: written against Nordic's `hello_axon` sample and syntax-checked on a PC; NOT built or run on hardware.**
The compiled models, the compiler's numbers and the simulator check are in `../export_out/axon/AXON_RESULTS.md`.
Expect to fix a build detail or two the first time.

Same job and same serial protocol as `../board_fw/` (Cortex-M33 + TensorFlow Lite Micro), so the same host script drives both.
Differences: the model is the **minimized 100 Hz model** (1,000 int8 samples per ECG) compiled by Nordic's Axon compiler, and the
board target must be the **B revision** chip, because only the nRF54LM20B has an Axon NPU.

## What is here

| file | role |
| --- | --- |
| `src/main.c` | Zephyr app: waits for a window on the console UART, checks the CRC, runs the Axon model (`nrf_axon_nn_model_infer_sync`), answers with the int8 logit and the time in ms and microseconds |
| `src/generated/nrf_axon_model_ecg_sex_w50_b10_.h`, `..._w25_.h` | the compiled models (made by the Axon compiler; see `AXON_RESULTS.md` to re-make them) |
| `boards/nrf54lm20dk_nrf54lm20b_cpuapp.overlay` | switches the Axon peripheral on (`&axon { status = "okay"; };`) |
| `prj.conf`, `Kconfig`, `CMakeLists.txt` | config: Axon on, interlayer RAM 49,000 B, console off (the UART carries our binary protocol), model choice |

## Build and flash (nRF Connect SDK terminal)

The Axon driver and compiler come from Nordic's **Edge AI add-on** (the `sdk-edge-ai` folder next to this one is a checkout of it).
Make it part of your west workspace the way its README says, then:

```
west build -b nrf54lm20dk/nrf54lm20b/cpuapp board_fw_axon -p 2>&1 | tee build.log
west flash
```

To build the smaller backup model instead, add `-- -DCONFIG_ECG_MODEL_W25=y` (or uncomment that line in `prj.conf`).
If the build stops with "nrf_axon_interlayer_buffer TOO SMALL", `CONFIG_NRF_AXON_INTERLAYER_BUFFER_SIZE` in `prj.conf` is below the
model's need (49,000 for w50_b10, 32,640 for w25).

## Talk to it

```
python board_runner.py ports
python board_runner.py run --engine axon --port <the DK's first virtual COM port> --n 20 --build-log build.log
# for w25:  add  --tflite export_out/axon/ecg_small_w25_int8.tflite --boardset export_out/small/boardset_small_w25.npz
```

The runner sends the windows quantized with the model's input scale and zero point (the board reports the zero point and the runner
checks it), then prints accuracy/AUC for fp32, int8 on the PC, and int8 on the board, how often the board output equals the PC int8
output, and the per-ECG time. One ECG is 1,000 bytes, so the serial transfer (about 0.1 s at 115200 baud) will now take longer than the inference.
A correct port gives outputs within 1-2 int8 steps of the PC (the simulator saw at most 1).

## If something is wrong

* `status=axon_init_fail` / `model_validate_fail` in the INFO line: the Axon peripheral is not enabled (check the overlay is picked up, board target is `.../nrf54lm20b/...`) or the driver version is older than the model needs (the headers require Axon driver version 1.5.1 or newer).
* `FAULT ...` line: a CPU fault; the line gives pc/lr and the fault registers.
* Silence: the console UART is used for the protocol, so no log output appears; use the DK's first virtual COM port. `CONFIG_LOG=n` is deliberate, since the log would corrupt the protocol.
