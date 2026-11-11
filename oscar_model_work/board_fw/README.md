# board_fw -- int8 ECG sex model on the nRF54LM20 DK (Cortex-M33 CPU, TensorFlow Lite Micro)

**Status: built, flashed and run on an nRF54LM20 DK (nRF Connect SDK v3.4.1, TFLM from zephyrproject-rtos/tflite-micro).**
One ECG with the 540 MMAC model took 633.9 s using TFLM's reference kernels. The CMSIS-NN kernels are switched off in `prj.conf`
because CMSIS-NN's Pad kernel aborted on this model; the minimized models use no PAD op, so it is worth trying them again.
The crash reporter in `main.cc` prints a `FAULT`/`ABORT` line over the UART (use `arm-zephyr-eabi-addr2line` on the address).
Models that use depthwise convolutions (`*_sep`) need `resolver.AddDepthwiseConv2D()` and a larger `MicroMutableOpResolver`.

This runs on the Arm CPU, not the Axon NPU (Axon would need the model retrained for <=1024 input samples;
that belongs to the minimization step).

## What is here

| file | role |
|---|---|
| `src/main.cc` | Zephyr app: waits for a window on the console UART, checks CRC, runs TFLM, answers with the int8 logit and ms |
| `src/model_data.cc`, `src/model_config.h` | **generated** by `python board_runner.py prepare` (the .tflite as a C array, arena size) |
| `prj.conf`, `CMakeLists.txt` | Zephyr/TFLM config |

## 1. Generate the model files

```
python board_runner.py prepare
```

Prints the CRC32 the board must report back (`model_crc32`). Re-run it whenever the `.tflite` changes.

## 2. Build and flash (in an nRF Connect SDK terminal)

```
# once: make the TFLM module part of the west workspace (Zephyr's tflite-micro sample README)
west config manifest.project-filter -- +tflite-micro
west update

west boards | grep nrf54lm20            # pick the target that matches the DK's chip revision (A or B)
west build -b nrf54lm20dk/nrf54lm20b/cpuapp board_fw -p 2>&1 | tee build.log
west flash
```

The `Memory region` table at the end of the build is the **real flash/RAM of the whole firmware**;
`board_runner.py run --build-log build.log` reports it.

## 3. Talk to it

```
python board_runner.py ports
python board_runner.py run --port <the DK's first virtual COM port> --n 2 --build-log build.log
```

Start with `--n 2` to see how long ONE inference takes (the run prints an ETA after window 1), then scale up
(`--n 20`, `--n 100`). A window is 5000 bytes at 115200 baud, about 0.5 s of transfer.

Speed: the model is 540 MMAC. With TFLM's plain reference kernels that can take a long time on a Cortex-M33
(possibly minutes per ECG). To speed it up, add the `cmsis-nn` module to the west workspace and uncomment
`CONFIG_TENSORFLOW_LITE_MICRO_CMSIS_NN_KERNELS=y` in `prj.conf`. Both numbers are worth recording; they are
exactly the latency the minimization step is trying to reduce.

## What "it works" means

`board_runner.py run` prints, for the same windows: fp32 (PC), int8 (PC) and int8 (board) accuracy/AUC, and
how often the board output equals the PC int8 output. A correct port gives the same male/female decision
almost always (rounding can differ by 1-2 int8 steps, especially with CMSIS-NN); a max difference of more than
a few steps means something is wrong (see below). Accuracy on a few dozen windows is only a smoke test; the
reliable accuracy number comes from `eval_host.py` on the full test set.

## Troubleshooting

* **Build: tflite-micro headers not found** -- the module is not in your workspace (step 2) or your NCS version
  names/places it differently; check `west list`.
* **Build: board target not found** -- use the exact string from `west boards | grep nrf54lm20`.
* **Build: region RAM overflowed** -- lower `MODEL_ARENA_BYTES` in `model_config.h` (only if the board reports
  `arena_used` well below it) or reduce `CONFIG_MAIN_STACK_SIZE`.
* **No answer from the board** -- try the DK's other virtual COM port; press the DK's reset button; add `--rtscts`.
  If the app returns at once, `device_is_ready(uart)` failed: the console UART node is not enabled for this board.
* **`status=alloc_fail_raise_arena`** -- raise `--arena-kib` in `prepare` (it is 10% above the estimated peak + 32 KiB).
* **`status=op_resolver`** -- more ops were registered than the resolver holds (`MicroMutableOpResolver<7>`); the model
  uses PAD, CONV_2D, MAX_POOL_2D, ADD, MEAN, FULLY_CONNECTED, RESHAPE.
* **`status=bad_input_tensor` / `schema_version`** -- the .tflite and the TFLM version disagree; regenerate with `prepare`
  and make sure TFLM is a recent version.
* **`ERR crc`** -- transfer noise; the runner retries automatically. Frequent => lower the baud rate in the devicetree.
* **Board output differs from PC int8 by many steps** -- a kernel or layout mismatch (first suspect: the explicit PAD ops
  or the MEAN op in the TFLM version you build with). Report the `max |dq|` and the INFO line.
* TFLM error messages are not printed because the console is switched off for the binary protocol. To see them,
  re-enable the console on a second UART in `prj.conf` / an overlay.
