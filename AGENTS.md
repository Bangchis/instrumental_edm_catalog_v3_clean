# Runtime boundary

- Do not install packages, download audio, download model weights, or create
  runtime/model caches on the local Mac.
- The local Mac is only for code edits, tests that require no new dependency,
  git/GitHub operations, SSH routing, and transferring credentials explicitly
  authorized by the user.
- Run `apt`, `uv`, `pip`, `yt-dlp`, Demucs, Whisper, MIR, OpenRouter annotation,
  ACE-Step preprocessing/training/inference, and Hugging Face model downloads on
  the Vast server under `/workspace` or `/dev/shm` as documented in
  `PIPELINE.md`.
- Never commit or publish source audio, secrets, auth files, model caches, or
  preprocessing tensors.
