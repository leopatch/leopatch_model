# Small ECG sex models: overnight results

Test set: 14,653 ECGs, 3,000 patients. 95% intervals resample PATIENTS. Threshold for each model = Youden J on the validation set. Device: mps.

| model | MACs | x fewer | params | int8 weights | act. RAM (est.) | test AUC [95% CI] | dAUC vs current [95% CI] | accuracy | sens / spec | int8 AUC | epochs | train min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **current (500 Hz)** | 541 M | 1x | 1.45 M | 1418 KiB | ~320 KiB | 0.8383 [0.820, 0.856] | - | 75.0% | 72 / 79 | - | - | - |
| w50 | 38.6 M | 14x | 261 K | 255 KiB | 47 KiB | 0.8221 [0.800, 0.841] | -0.0163 [-0.026, -0.007] | 73.8% | 74 / 73 | n/a | 60 | 9 |
| w50_sep | 8.3 M | 65x | 59 K | 58 KiB | 47 KiB | 0.8215 [0.799, 0.841] | -0.0169 [-0.026, -0.008] | 74.3% | 76 / 72 | n/a | 60 | 9 |
| w25 | 9.7 M | 56x | 65 K | 64 KiB | 23 KiB | 0.8236 [0.803, 0.843] | -0.0147 [-0.022, -0.008] | 74.1% | 73 / 75 | n/a | 60 | 3 |
| w100 | 154.1 M | 4x | 1042 K | 1018 KiB | 94 KiB | 0.8239 [0.802, 0.842] | -0.0144 [-0.024, -0.006] | 74.1% | 73 / 75 | n/a | 60 | 25 |
| w50_nokd | 38.6 M | 14x | 261 K | 255 KiB | 47 KiB | 0.8164 [0.794, 0.838] | -0.0220 [-0.034, -0.011] | 73.7% | 74 / 74 | n/a | 60 | 9 |
| w50_b10 | 18.1 M | 30x | 97 K | 95 KiB | 47 KiB | 0.8256 [0.805, 0.843] | -0.0128 [-0.020, -0.006] | 74.4% | 75 / 74 | n/a | 60 | 6 |
| w75_sep | 18.2 M | 30x | 130 K | 127 KiB | 70 KiB | 0.8191 [0.799, 0.838] | -0.0192 [-0.028, -0.011] | 73.8% | 72 / 76 | n/a | 60 | 14 |

## Reading it

* No variant stayed within 0.01 AUC. Best was **w50_b10** (AUC 0.8256, dAUC -0.0128).
* A difference smaller than its confidence interval is not a real difference. The dAUC interval is the thing to trust.
* 'act. RAM (est.)' is a rough int8 estimate; the board reports the real TFLM arena.
* w50: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w50.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
* w50_sep: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w50_sep.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
* w25: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w25.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
* w100: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w100.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
* w50_nokd: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w50_nokd.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
* w50_b10: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w50_b10.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
* w75_sep: skipped (tensorflow not installed): run  python small_ecg.py export --ckpt /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/small_w75_sep.pt --calib /Users/oscarzhang/Desktop/leopatch_model-main/export_out/small/calib_windows_small.npy
