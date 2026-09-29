"""Download candidate ASR models into ./models (CTranslate2 format for faster-whisper).

Models already in CTranslate2 format are downloaded as-is; plain transformers
checkpoints are downloaded and converted with ct2-transformers-converter
(run from .venv-convert, which has torch + transformers).
"""
import subprocess
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
CONVERTER = ROOT / ".venv-convert" / "Scripts" / "ct2-transformers-converter.exe"

# name -> (repo, needs_conversion)
CANDIDATES = {
    "turbo": ("deepdml/faster-whisper-large-v3-turbo-ct2", False),
    "large-v3": ("Systran/faster-whisper-large-v3", False),
    "fa-amirmohseni-large-v3": ("AmirMohseni/whisper-large-v3-persian-ct2-int8", False),
    "fa-vhdm-turbo": ("vhdm/whisper-large-fa-v1", True),
    "fa-nezamisafa-large-v3": ("nezamisafa/whisper-persian-v4", True),
}

SKIP = ["runs/*", "*.tfevents*", "training_args.bin", "*.msgpack", "*.h5", "*.ot"]


def main(names):
    MODELS.mkdir(exist_ok=True)
    for name in names:
        repo, convert = CANDIDATES[name]
        out = MODELS / name
        if (out / "model.bin").exists():
            print(f"[skip] {name} already present", flush=True)
            continue
        print(f"[download] {name} <- {repo}", flush=True)
        if not convert:
            snapshot_download(repo, local_dir=out, ignore_patterns=SKIP)
            continue
        raw = MODELS / "_raw" / name
        snapshot_download(repo, local_dir=raw, ignore_patterns=SKIP)
        print(f"[convert] {name}", flush=True)
        subprocess.run(
            [str(CONVERTER), "--model", str(raw), "--output_dir", str(out),
             "--quantization", "float16", "--force",
             "--copy_files", "tokenizer_config.json", "preprocessor_config.json"],
            check=True,
        )
        # faster-whisper needs tokenizer.json; transformers can build it from vocab/merges
        if not (out / "tokenizer.json").exists():
            subprocess.run(
                [str(CONVERTER.parent / "python.exe"), "-c",
                 "import sys; from transformers import WhisperTokenizerFast as T; "
                 "T.from_pretrained(sys.argv[1]).backend_tokenizer.save(sys.argv[2])",
                 str(raw), str(out / "tokenizer.json")],
                check=True,
            )
    print("[done]", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or list(CANDIDATES))
