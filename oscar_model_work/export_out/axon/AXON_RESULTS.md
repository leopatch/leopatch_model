# Running the minimized sex model on the Axon NPU: what was done and what is (not) known

**Status: compiled and simulated on a PC. NOT built or run on the board** (no board was connected). Everything marked
"estimate" below comes from Nordic's compiler, not from a measurement on the DK.

## What was done

1. The two best minimized 100 Hz models (`w50_b10`, `w25`) were exported to **int8 TensorFlow Lite**
   (`python small_ecg.py export ...`, see `small_ecg.py`). Each model exists in two layouts with identical maths:
   * `ecg_small_<name>_int8.tflite`: signal along the height `(1, 1000, 1, 1)`. This is the PC/TFLM reference.
   * `ecg_small_<name>_axon_int8.tflite`: signal along the width `(1, 1, 1000, 1)` (`--wide`). Axon keeps a tensor row in
     32-bit-aligned memory, so a long, thin signal must lie along the width. This is the file the Axon compiler reads.
   The two give bit-identical outputs (checked on 200 windows).
2. Nordic's **Axon NN compiler** (`sdk-edge-ai/tools/axon/compiler`, version 2.0.1) turned the `_axon_int8.tflite` into the
   C headers in `board_fw_axon/src/generated/`. All 10 layers compiled as Axon operations.
3. The compiler's x86 **simulator** ran the compiled Axon models on 199 real test windows and compared them with the TFLite
   int8 model on the same int8 inputs.
4. `board_fw_axon/` is a firmware for the nRF54LM20B DK that runs the compiled model and speaks the same serial protocol
   as `board_fw/`; `board_runner.py run --engine axon` drives it.

The original 500 Hz / 5,000-sample model **cannot** run on Axon (a tensor may be at most 1,024 wide). The 100 Hz / 1,000-sample
minimized models fit; this is one more reason the minimization step mattered.

## Compiler numbers (from the compiler, not measured on hardware)

| | w50_b10 (recommended) | w25 (backup) |
| --- | --- | --- |
| Model weights (flash) | 96,516 B | 65,156 B |
| Axon command buffer (flash) | 83,240 B | 74,888 B |
| **Flash for the model** | **179,756 B (176 KiB)** | **140,044 B (137 KiB)** |
| Axon interlayer RAM (scratch) | 49,000 B (48 KiB) | 32,640 B (32 KiB) |
| Partial-sum buffer | 0 | 0 |
| Compiler's inference estimate | 9,791,186 cycles | 5,329,429 cycles |
| ... in milliseconds IF the cycle clock is 128 MHz | **about 76 ms** | **about 42 ms** |

The compiler documents its estimate as "system clock cycles"; the 128 MHz conversion is my assumption, so treat 76 ms and
42 ms as rough estimates (the real value includes the Axon's start-up and memory waits and must be measured with
`board_runner.py run --engine axon`, which prints the on-board time in microseconds-resolution milliseconds).
For comparison, the original 8-bit model took 633.9 s per ECG on the Cortex-M33 CPU (measured). The minimized models were not
timed on the CPU, so there is no measured CPU-vs-Axon comparison for the same model yet. (My earlier 5-35 ms guess was too optimistic.)

## Does the Axon model agree with the TFLite int8 model? (simulator, 199 test windows)

See `axon_sim_check.json`.

| | w50_b10 | w25 |
| --- | --- | --- |
| Outputs identical to TFLite int8 | 94.0% | 84.9% |
| Outputs within 1 int8 step | 100% | 100% |
| Largest difference | 1 step (about 0.05 in logit) | 1 step |
| Same male/female decision as TFLite int8 | 99.5% | 100% |
| AUC on these 199 windows: fp32 / TFLite int8 / Axon | 0.869 / 0.872 / 0.872 | 0.857 / 0.863 / 0.863 |

So putting the model on Axon should change almost nothing relative to the 8-bit model. Only 199 windows were checked, so the AUCs
above only show that nothing breaks; they are not a replacement for the full-test-set numbers in `RESULTS_small.md`
(those are fp32; the 8-bit scores of the minimized models on the whole test set were not computed).

## Re-making the headers (only needed if you retrain or change a model)

The headers in `board_fw_axon/src/generated/` are already made. To make new ones:

```
# 1. export the int8 files (in the repo root)
python small_ecg.py export --ckpt export_out/small/small_w50_b10.pt --calib export_out/small/calib_windows_small.npy \
       --out export_out/axon/ecg_small_w50_b10_int8.tflite
python small_ecg.py export --ckpt export_out/small/small_w50_b10.pt --calib export_out/small/calib_windows_small.npy \
       --out export_out/axon/ecg_small_w50_b10_axon_int8.tflite --wide

# 2. compile (needs the Nordic Edge AI add-on checked out as sdk-edge-ai/, and its Python deps: see
#    sdk-edge-ai/tools/axon/compiler/scripts/requirements.txt -- use a venv with numpy < 2, TensorFlow 2.19)
cd export_out/axon
export COMPILER_ROOT_FOLDER=<repo>/sdk-edge-ai/tools/axon/compiler
PYTHONPATH=$COMPILER_ROOT_FOLDER/scripts python $COMPILER_ROOT_FOLDER/scripts/axons_ml_nn_compiler_executor.py compile_w50_b10.yaml
# -> outputs/nrf_axon_model_ecg_sex_w50_b10_.h   (copy it to board_fw_axon/src/generated/)
```

The headers here were made on Linux with a scratch copy of the compiler where `int(np.round(x))` on 1-element arrays was
changed to a scalar extraction, because the stock scripts fail on NumPy 2. With NumPy 1.x (what the requirements pin for
TensorFlow 2.19) they should run unmodified; that was not tested. The compiler library for macOS (Apple silicon) is in
`sdk-edge-ai/tools/axon/compiler/bin/Darwin`.

## Not done / open

* Never built (`west build`) or run on a board. The firmware was syntax-checked against the real Nordic headers and the generated
  headers on a PC with stand-ins for the Zephyr headers, which is not a build.
* No measured Axon speed, no power/energy measurement.
* Newborn data: these models were trained on adult MIMIC-IV-ECG, the same caveat as everything else here.
