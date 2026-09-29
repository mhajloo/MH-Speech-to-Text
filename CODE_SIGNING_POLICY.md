# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

Windows releases of MH-Speech to Text are built from this repository by GitHub Actions
([build.yml](.github/workflows/build.yml)) and signed through SignPath. Only binaries built this
way from the public source code are signed.

## Team roles

- Committers and reviewers: [Mohammad Hajloo](https://github.com/mhajloo)
- Approvers: [Mohammad Hajloo](https://github.com/mhajloo)

## Privacy policy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it.

Speech recognition runs entirely on the user's computer; audio and dictated text never leave it.
The only network access is the first-run download of the speech model (and, on PCs with an NVIDIA
graphics card, NVIDIA's cuBLAS library), which the user starts in the setup wizard. The files come
from www.hajloo.ir, falling back to Hugging Face or PyPI.
