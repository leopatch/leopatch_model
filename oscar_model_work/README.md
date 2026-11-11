# Oscar Model Work: the ECG sex model, minimized and run on the nRF54LM20 DK

This folder adds four things to the LEO PATCH model repo:

1. The 1-lead (V3) ECG sex model from `models/2026.10.08/`, converted to 8-bit and **run on the nRF54LM20 DK**.
2. **Seven smaller models** (trained at 100 Hz, with a teacher-student loss) and how they compare.
3. **Axon NPU version** of the two best small models: 8-bit files, compiled Axon headers, and a firmware for the nRF54LM20B DK (compiled and simulated on a PC, **not yet run on the board**).
4. The scripts to reproduce all of it.

The sex model is only a practice task to prove the pipeline. The real goal is heart-defect screening on newborns.

## Where the models are

| What | File | Notes |
| --- | --- | --- |
| Original model (PyTorch) | `../models/2026.10.08/2_best_ecg_sex_leadv3_finetuned_15epochs.pth` | 1.45 M parameters, 541 M MACs, 5,000 samples (500 Hz) |
| Original model, 8-bit | `export_out/ecg_sex_leadv3_int8.tflite` | 1.5 MB. This is the one that runs on the board. |
| Minimized models (PyTorch) | `export_out/small/small_<name>.pt` | `w50_b10` is the recommended one. 1,000 samples (100 Hz). |

The two best minimized models (`w50_b10`, `w25`) are also exported to 8-bit in `export_out/axon/` (see the Axon section below).
Each `.pt` file holds a dict with `cfg`, `state`, `name` and `thr_prob`
(the decision cutoff). Load one like this (see `small_ecg.py`):

```python
import torch, small_ecg as S
ck = torch.load("export_out/small/small_w50_b10.pt", map_location="cpu", weights_only=False)
model = S.SmallECG(ck["cfg"]); model.load_state_dict(ck["state"]); model.eval()
# x: float32 array (N, 1000): lead V3, 10 s resampled to 100 Hz, each ECG z-scored
prob = torch.sigmoid(model(torch.from_numpy(x)))
pred = prob >= ck["thr_prob"]
```

## Results

Test set: 14,653 ECGs from 3,000 patients (split by patient). AUC is the main score (0.5 = coin flip, 1.0 = perfect).
"Change" is the AUC difference from the original model. The 95% range on AUC is about plus or minus 0.02.

| Model | AUC (change) | Accuracy | MACs (millions) | Times fewer | 8-bit weights (KiB) |
| --- | --- | --- | --- | --- | --- |
| Original (500 Hz) | 0.838 | 75.0% | 541 | 1 | 1,418 |
| **w50_b10 (recommended)** | **0.826 (-0.013)** | **74.4%** | **18.1** | **30** | **95** |
| w100 | 0.824 (-0.014) | 74.1% | 154.1 | 4 | 1,018 |
| w25 | 0.824 (-0.015) | 74.1% | 9.7 | 56 | 64 |
| w50 | 0.822 (-0.016) | 73.8% | 38.6 | 14 | 255 |
| w50_sep | 0.822 (-0.017) | 74.3% | 8.3 | 65 | 58 |
| w75_sep | 0.819 (-0.019) | 73.8% | 18.2 | 30 | 127 |
| w50_nokd (no teacher) | 0.816 (-0.022) | 73.7% | 38.6 | 14 | 255 |

Full table, intervals and training logs: `export_out/small/RESULTS_small.md`, `results_small.json`, `train_small.log`.

**On the board (original 8-bit model, TensorFlow Lite Micro on the Cortex-M33 CPU):**
633.9 s per ECG, model working memory 334,148 bytes, program storage 1.59 MB (76%), RAM 423 KB (81%).
The board's output matched the PC's 8-bit output to within 2 steps. See `export_out/board_results_leadv3.json`.

Not measured yet: the 8-bit scores of the minimized models on the whole test set, and their time on the board.

## Axon NPU (nRF54LM20B)

The nRF54LM20B chip has a neural-network accelerator (Axon). The 500 Hz original cannot run on it (a tensor may be at most 1,024
wide), but the 100 Hz minimized models can. Details, numbers and how to re-make everything: `export_out/axon/AXON_RESULTS.md`.

| | w50_b10 (recommended) | w25 (backup) |
| --- | --- | --- |
| Flash for the model | 176 KiB | 137 KiB |
| Axon scratch RAM | 48 KiB | 32 KiB |
| Compiler's speed estimate (not measured) | 9.8 M cycles, about 76 ms at 128 MHz | 5.3 M cycles, about 42 ms |
| Axon output vs 8-bit TFLite (simulator, 199 test windows) | 94% identical, all within 1 step | 85% identical, all within 1 step |

* `export_out/axon/*_int8.tflite`: the 8-bit models. `*_axon_int8.tflite` is the same model with the signal laid out along the width, which is what Axon needs.
* `board_fw_axon/`: firmware for the DK, same serial protocol as `board_fw/`. **Never built or run on hardware**; build and flash steps in `board_fw_axon/README.md`.
* `board_runner.py run --engine axon --port <port>` drives it and prints the on-board time and the accuracy check.

## How to run things

Needs Python with numpy, pandas, h5py, scipy and PyTorch (training); TensorFlow or `ai-edge-litert` (8-bit export and checks).

```
# evaluate the original model (and the 8-bit file) on the test set
python eval_host.py --dataset-dir "<folder with the dataset>" --tflite export_out/ecg_sex_leadv3_int8.tflite

# retrain the minimized models (about 1.5 hours on an Apple-silicon Mac)
python train_small.py --budget-min 170        # add --quick for a 2-minute smoke test

# put the original model on the board (CPU)
python board_runner.py prepare                # writes board_fw/src/model_data.cc
# build and flash with the nRF Connect SDK, then:
python board_runner.py run --port <the DK's serial port> --n 2

# or put a minimized model on the board (Axon NPU, needs the nRF54LM20B DK); the 8-bit and Axon files are already made
west build -b nrf54lm20dk/nrf54lm20b/cpuapp board_fw_axon -p && west flash
python board_runner.py run --engine axon --port <the DK's serial port> --n 20
```

Board build and flash steps and troubleshooting: `board_fw/README.md` (CPU) and `board_fw_axon/README.md` (Axon).

## Data

The data is not in this repo: `mimic_iv_ecg_full.h5` (about 50 GB) and the metadata CSV, built from MIMIC-IV-ECG.
The h5 file needs PhysioNet credentialed access. Put it in `Dataset for ECG/` next to the scripts, or pass `--dataset-dir`.
Test windows taken from it (`export_out/small/boardset_*.npz`, `export_out/axon/xq_*.npy`) are left out of the repo on purpose; `board_runner.py run` needs a `boardset_*.npz`, which `train_small.py` regenerates.
The ECGs are from adult patients, not newborns, so these results say nothing yet about newborn accuracy.
