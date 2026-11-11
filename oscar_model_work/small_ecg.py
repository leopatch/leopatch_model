#!/usr/bin/env python3
"""
small_ecg.py -- the SMALL 1-lead ECG sex models for the nRF54LM20.
PyTorch definition, cost counting, BatchNorm folding, Keras twin and int8 TFLite export.
(train_small.py trains these; this file can also export a saved checkpoint by itself.)

Design choices that matter for the board:
  * input is 100 Hz x 10 s = 1000 samples (the old model used 500 Hz = 5000), which is also <= 1024 for Axon.
  * every convolution uses TensorFlow-style 'SAME' padding in PyTorch too (extra zero on the RIGHT for stride 2),
    so the TFLite model needs NO separate PAD ops (the PAD op is what crashed the CMSIS-NN build).
  * only ops TFLite Micro already runs for us: CONV_2D, DEPTHWISE_CONV_2D, MAX_POOL_2D, ADD, MEAN, FULLY_CONNECTED.

CLI:  python small_ecg.py export --ckpt export_out/small/small_w50.pt --calib export_out/small/calib_windows_small.npy
"""
import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
import torch.nn.functional as F  # noqa: E402

L_IN = 1000            # 10 s at 100 Hz

# name -> architecture. widths = channels of the three stages (old model: 64/128/256 at 500 Hz).
VARIANTS = {
    "w50":      dict(widths=(32, 64, 128), k=5, stem_k=7, blocks=(1, 1), sep=False),   # half width
    "w50_sep":  dict(widths=(32, 64, 128), k=5, stem_k=7, blocks=(1, 1), sep=True),    # + depthwise-separable convs
    "w25":      dict(widths=(16, 32, 64), k=5, stem_k=7, blocks=(1, 1), sep=False),    # quarter width
    "w100":     dict(widths=(64, 128, 256), k=5, stem_k=7, blocks=(1, 1), sep=False),  # old widths, only 100 Hz
    "w50_nokd": dict(widths=(32, 64, 128), k=5, stem_k=7, blocks=(1, 1), sep=False),   # ablation: no distillation
    "w50_b10":  dict(widths=(32, 64, 128), k=5, stem_k=7, blocks=(1, 0), sep=False),   # drop the last residual block
    "w75_sep":  dict(widths=(48, 96, 192), k=5, stem_k=7, blocks=(1, 1), sep=True),
}
NO_KD = {"w50_nokd"}


# ======================================================================================
# PyTorch model
# ======================================================================================
def same_pad(length, k, s):
    """TensorFlow 'SAME' padding: (left, right). The odd extra zero goes on the right."""
    out = math.ceil(length / s)
    total = max((out - 1) * s + k - length, 0)
    return total // 2, total - total // 2


class SameConv(nn.Module):
    def __init__(self, cin, cout, k, s=1, groups=1):
        super().__init__()
        self.k, self.s = k, s
        self.conv = nn.Conv1d(cin, cout, k, stride=s, groups=groups, bias=False)

    def forward(self, x):
        left, right = same_pad(x.shape[-1], self.k, self.s)
        return self.conv(F.pad(x, (left, right)))


class Unit(nn.Module):
    """conv+BN(+ReLU), or depthwise(k)+BN+ReLU followed by pointwise(1)+BN(+ReLU) when sep=True."""

    def __init__(self, cin, cout, k, s, relu, sep):
        super().__init__()
        self.relu = relu
        if sep and k > 1:
            self.dw = SameConv(cin, cin, k, s, groups=cin)
            self.bn1 = nn.BatchNorm1d(cin)
            self.pw = SameConv(cin, cout, 1, 1)
        else:
            self.dw = None
            self.conv = SameConv(cin, cout, k, s)
        self.bn2 = nn.BatchNorm1d(cout)

    def forward(self, x):
        if self.dw is not None:
            x = F.relu(self.bn1(self.dw(x)))
            x = self.bn2(self.pw(x))
        else:
            x = self.bn2(self.conv(x))
        return F.relu(x) if self.relu else x


class ResBlock(nn.Module):
    def __init__(self, c, k, sep):
        super().__init__()
        self.a = Unit(c, c, k, 1, True, sep)
        self.b = Unit(c, c, k, 1, False, sep)

    def forward(self, x):
        return F.relu(x + self.b(self.a(x)))


class SmallECG(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = dict(cfg)
        c1, c2, c3 = cfg["widths"]
        k, sep = cfg["k"], cfg["sep"]
        n1, n2 = cfg["blocks"]
        self.stem = Unit(1, c1, cfg["stem_k"], 1, True, False)          # 1000 -> 1000
        self.down1 = Unit(c1, c2, k, 2, True, sep)                      # after maxpool(2): 500 -> 250
        self.res1 = nn.ModuleList([ResBlock(c2, k, sep) for _ in range(n1)])
        self.down2 = Unit(c2, c3, k, 2, True, sep)                      # 250 -> 125
        self.res2 = nn.ModuleList([ResBlock(c3, k, sep) for _ in range(n2)])
        hidden = max(16, c3 // 4)
        self.fc1 = nn.Linear(c3, hidden)
        self.fc2 = nn.Linear(hidden, 1)

    def forward(self, x):                      # x: (B, 1000) z-scored -> (B,) logit
        h = self.stem(x[:, None, :])
        h = F.max_pool1d(h, 2, 2)
        h = self.down1(h)
        for b in self.res1:
            h = b(h)
        h = self.down2(h)
        for b in self.res2:
            h = b(h)
        return self.fc2(F.relu(self.fc1(h.mean(-1)))).squeeze(-1)


def make_model(name_or_cfg):
    cfg = VARIANTS[name_or_cfg] if isinstance(name_or_cfg, str) else name_or_cfg
    return SmallECG(cfg)


# ======================================================================================
# Cost: parameters (BN folded), MACs, rough int8 activation RAM
# ======================================================================================
def cost(model, length=L_IN):
    macs = 0
    hooks = []

    def hook(m, _i, o):
        nonlocal macs
        macs += int(o.shape[-1]) * m.out_channels * (m.in_channels // m.groups) * m.kernel_size[0]

    for m in model.modules():
        if isinstance(m, nn.Conv1d):
            hooks.append(m.register_forward_hook(hook))
    was = model.training
    model.eval()
    with torch.no_grad():
        dev = next(model.parameters()).device
        model(torch.zeros(1, length, device=dev))
    for h in hooks:
        h.remove()
    model.train(was)
    params = 0
    for m in model.modules():
        if isinstance(m, nn.Conv1d):
            params += m.weight.numel() + m.out_channels            # folded BN supplies the bias
        elif isinstance(m, nn.Linear):
            params += m.weight.numel() + m.bias.numel()
            macs += m.weight.numel()
    return params, macs


def activation_bytes(cfg, length=L_IN):
    """Rough peak of live int8 activations (input + output + skip held for residuals), no allocator overhead."""
    c1, c2, c3 = cfg["widths"]
    k, sep = cfg["k"], cfg["sep"]
    peaks = []

    def unit(cin, cout, lin, s, extra, is_sep):
        lout = math.ceil(lin / s)
        if is_sep:
            mid = cin * lout
            peaks.append(cin * lin + mid + extra)
            peaks.append(mid + cout * lout + extra)
        else:
            peaks.append(cin * lin + cout * lout + extra)
        return lout

    l = unit(1, c1, length, 1, 0, False)
    l //= 2
    peaks.append(c1 * (l * 2) + c1 * l)                              # maxpool in + out
    l = unit(c1, c2, l, 2, 0, sep)
    for _ in range(cfg["blocks"][0]):
        unit(c2, c2, l, 1, 0, sep)
        unit(c2, c2, l, 1, c2 * l, sep)
        peaks.append(3 * c2 * l)
    l = unit(c2, c3, l, 2, 0, sep)
    for _ in range(cfg["blocks"][1]):
        unit(c3, c3, l, 1, 0, sep)
        unit(c3, c3, l, 1, c3 * l, sep)
        peaks.append(3 * c3 * l)
    return int(max(peaks))


# ======================================================================================
# BN folding + Keras twin + int8 export
# ======================================================================================
def _fold(conv, bn):
    w = conv.conv.weight.detach().cpu().numpy().astype(np.float64)            # (cout, cin/groups, k)
    g = bn.weight.detach().cpu().numpy().astype(np.float64)
    var = bn.running_var.detach().cpu().numpy().astype(np.float64)
    mu = bn.running_mean.detach().cpu().numpy().astype(np.float64)
    beta = bn.bias.detach().cpu().numpy().astype(np.float64)
    s = g / np.sqrt(var + bn.eps)
    return (w * s[:, None, None]).astype(np.float32), (beta - mu * s).astype(np.float32)


def build_keras(model, length=L_IN):
    import tensorflow as tf
    K = tf.keras.layers
    model = model.eval().cpu()

    def unit(x, u):
        act = "relu" if u.relu else None
        if u.dw is not None:
            w, b = _fold(u.dw, u.bn1)                                            # (cin,1,k)
            lay = K.DepthwiseConv2D((u.dw.k, 1), strides=(u.dw.s, 1), padding="same", activation="relu")
            x = lay(x)
            lay.set_weights([w.transpose(2, 0, 1)[:, None, :, :], b])            # (k,1,cin,1)
            w, b = _fold(u.pw, u.bn2)                                            # (cout,cin,1)
            lay = K.Conv2D(w.shape[0], (1, 1), activation=act)
            x = lay(x)
            lay.set_weights([w.transpose(2, 1, 0)[:, None, :, :], b])            # (1,1,cin,cout)
        else:
            w, b = _fold(u.conv, u.bn2)                                          # (cout,cin,k)
            lay = K.Conv2D(w.shape[0], (u.conv.k, 1), strides=(u.conv.s, 1), padding="same", activation=act)
            x = lay(x)
            lay.set_weights([w.transpose(2, 1, 0)[:, None, :, :], b])            # (k,1,cin,cout)
        return x

    def res(x, blk):
        y = unit(unit(x, blk.a), blk.b)
        return K.ReLU()(K.Add()([x, y]))

    inp = tf.keras.Input(shape=(length, 1, 1), batch_size=1, name="ecg")
    x = unit(inp, model.stem)
    x = K.MaxPooling2D((2, 1), strides=(2, 1), padding="valid")(x)
    x = unit(x, model.down1)
    for b in model.res1:
        x = res(x, b)
    x = unit(x, model.down2)
    for b in model.res2:
        x = res(x, b)
    x = K.GlobalAveragePooling2D()(x)
    lay = K.Dense(model.fc1.out_features, activation="relu")
    x = lay(x)
    lay.set_weights([model.fc1.weight.detach().numpy().T, model.fc1.bias.detach().numpy()])
    lay = K.Dense(1)
    out = lay(x)
    lay.set_weights([model.fc2.weight.detach().numpy().T, model.fc2.bias.detach().numpy()])
    return tf.keras.Model(inp, out, name="ecg_sex_small")


def quantize(kmodel, calib):
    import tensorflow as tf
    length = kmodel.input_shape[1]

    def rep():
        for w in calib:
            yield [np.asarray(w, np.float32).reshape(1, length, 1, 1)]

    conv = tf.lite.TFLiteConverter.from_keras_model(kmodel)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


def export_int8(model, calib, out_path, check_x=None):
    """Fold BN, build the Keras twin, check it against PyTorch, quantize with real windows, write the .tflite."""
    km = build_keras(model, calib.shape[1])
    info = {}
    if check_x is not None:
        with torch.no_grad():
            ref = model.eval().cpu()(torch.from_numpy(np.asarray(check_x, np.float32))).numpy()
        got = np.concatenate([km.predict(np.asarray(x, np.float32).reshape(1, -1, 1, 1), verbose=0).reshape(-1)
                              for x in check_x])
        info["keras_vs_torch_max_abs"] = float(np.abs(ref - got).max())
    blob = quantize(km, calib)
    Path(out_path).write_bytes(blob)
    info["tflite_bytes"] = len(blob)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="int8-quantize a saved checkpoint")
    e.add_argument("--ckpt", required=True)
    e.add_argument("--calib", required=True, help="npy of z-scored 100 Hz validation windows (N,1000)")
    e.add_argument("--out", default=None)
    e.add_argument("--eval-x", default=None, help="npy of windows to run through the int8 model")
    e.add_argument("--eval-out", default=None, help="where to write the int8 logits (npy)")
    e.add_argument("--report", default=None, help="json with sizes / ops / memory")
    a = ap.parse_args()
    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    m = SmallECG(ck["cfg"])
    m.load_state_dict(ck["state"])
    calib = np.load(a.calib)
    out = a.out or str(Path(a.ckpt).with_name(f"ecg_small_{ck.get('name', 'model')}_int8.tflite"))
    info = export_int8(m, calib[:300], out, check_x=calib[:4])
    if a.eval_x or a.report:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import eval_host as eh
        if a.eval_x:
            lg, _ = eh.eval_tflite(out, np.load(a.eval_x))
            np.save(a.eval_out, lg)
        mem = eh.tflite_memory_report(out)
        info.update(ops=mem["ops"], peak_copy=mem["peak_copy"], peak_alias=mem["peak_alias"])
    if a.report:
        import json
        Path(a.report).write_text(json.dumps(info))
    print(info)
    print("wrote", out)


if __name__ == "__main__":
    main()
