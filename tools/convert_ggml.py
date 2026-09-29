"""Convert a Hugging Face Whisper checkpoint to whisper.cpp's GGML format (f16).

Based on whisper.cpp's models/convert-h5-to-ggml.py (MIT License), but reads the
safetensors file tensor by tensor instead of building the model in memory, and
accepts bfloat16 checkpoints: every bf16 value is exactly representable in f16,
so the f16 output holds the checkpoint's weights unchanged. Quantize the result
with whisper.cpp's quantize tool (tools/build_whispercpp.py builds it).

Usage (needs torch and safetensors, e.g. the .venv-convert environment):
  .venv-convert/Scripts/python tools/convert_ggml.py MODEL_DIR MEL_FILTERS.npz OUT.bin
MODEL_DIR holds config.json, vocab.json, added_tokens.json and model.safetensors;
MEL_FILTERS.npz is openai/whisper's whisper/assets/mel_filters.npz.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
import torch
from safetensors import safe_open

# Hugging Face layer names -> the OpenAI names whisper.cpp expects
CONV_MAP = {
    "self_attn.k_proj": "attn.key",
    "self_attn.q_proj": "attn.query",
    "self_attn.v_proj": "attn.value",
    "self_attn.out_proj": "attn.out",
    "self_attn_layer_norm": "attn_ln",
    "encoder_attn.q_proj": "cross_attn.query",
    "encoder_attn.v_proj": "cross_attn.value",
    "encoder_attn.out_proj": "cross_attn.out",
    "encoder_attn_layer_norm": "cross_attn_ln",
    "fc1": "mlp.0",
    "fc2": "mlp.2",
    "final_layer_norm": "mlp_ln",
    "encoder.layer_norm.bias": "encoder.ln_post.bias",
    "encoder.layer_norm.weight": "encoder.ln_post.weight",
    "encoder.embed_positions.weight": "encoder.positional_embedding",
    "decoder.layer_norm.bias": "decoder.ln.bias",
    "decoder.layer_norm.weight": "decoder.ln.weight",
    "decoder.embed_positions.weight": "decoder.positional_embedding",
    "decoder.embed_tokens.weight": "decoder.token_embedding.weight",
}
KEEP_F32 = {"encoder.conv1.bias", "encoder.conv2.bias",
            "encoder.positional_embedding", "decoder.positional_embedding"}


def bytes_to_unicode():
    """GPT-2's byte <-> unicode table used by Whisper's BPE vocabulary."""
    bs = (list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1))
          + list(range(ord("®"), ord("ÿ") + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


def ggml_name(name):
    parts = name.split(".")[1:]  # drop the "model." prefix
    if parts[1] == "layers":
        parts[1] = "blocks"
        sub = ".".join(parts[3:-1])
        if sub == "encoder_attn.k_proj":
            mapped = "attn.key" if parts[0] == "encoder" else "cross_attn.key"
        else:
            mapped = CONV_MAP[sub]
        return ".".join(parts[:3] + [mapped] + parts[-1:])
    joined = ".".join(parts)
    return CONV_MAP.get(joined, joined)


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    model_dir, mel_path, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    hp = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    vocab = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))
    max_length = hp.get("max_length") or hp.get("max_target_positions", 448)
    n_mels = hp["num_mel_bins"]
    with np.load(mel_path) as f:
        filters = f[f"mel_{n_mels}"].astype(np.float32)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as out, \
            safe_open(model_dir / "model.safetensors", framework="pt") as st:
        out.write(struct.pack("i", 0x67676D6C))  # "ggml"
        for key in ("vocab_size", "max_source_positions", "d_model", "encoder_attention_heads",
                    "encoder_layers"):
            out.write(struct.pack("i", hp[key]))
        out.write(struct.pack("i", int(max_length)))
        for key in ("d_model", "decoder_attention_heads", "decoder_layers", "num_mel_bins"):
            out.write(struct.pack("i", hp[key]))
        out.write(struct.pack("i", 1))  # f16
        out.write(struct.pack("ii", *filters.shape))
        out.write(filters.tobytes())

        byte_decoder = {v: k for k, v in bytes_to_unicode().items()}
        out.write(struct.pack("i", len(vocab)))
        for token, _ in sorted(vocab.items(), key=lambda kv: kv[1]):
            text = bytes(byte_decoder[c] for c in token)
            out.write(struct.pack("i", len(text)))
            out.write(text)

        count = 0
        for src in st.keys():
            if src == "proj_out.weight":  # tied to the token embedding
                continue
            name = ggml_name(src)
            data = st.get_tensor(src).to(torch.float32).squeeze().numpy()
            if name in ("encoder.conv1.bias", "encoder.conv2.bias"):
                data = data.reshape(data.shape[0], 1)
            if data.ndim < 2 or name in KEEP_F32:
                data, ftype = data.astype(np.float32), 0
            else:
                data, ftype = data.astype(np.float16), 1
            encoded = name.encode("utf-8")
            out.write(struct.pack("iii", data.ndim, len(encoded), ftype))
            for dim in reversed(data.shape):
                out.write(struct.pack("i", dim))
            out.write(encoded)
            out.write(np.ascontiguousarray(data).tobytes())
            count += 1
    print(f"{count} tensors -> {out_path} ({out_path.stat().st_size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
