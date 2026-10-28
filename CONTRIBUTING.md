# Contributing

Focus on fidelity before automation claims: keep original words, numbers,
conditions, attribution and user choices intact. A successful build is not an
independent listening certificate.

- Explain the user-visible problem and expected behavior.
- Reproduce with synthetic or explicitly shareable media. Do not attach private
  recordings, account logs, credentials, model caches or customer projects.
- Keep planning, semantic review, acoustic checks and final movie verification
  separate. Never loosen neighboring-word protection merely to make a test pass.
- Do not replace host planning with a hard-coded sentence recipe for one video.
- Keep new dependencies scoped, pinned and documented with upstream notices.
- Test both captions and titles independently, including both disabled. User
  confirmation must precede new-project rendering.
- Run `python -m unittest discover -s tests -v` in the prepared runtime. Packaging
  uses `scripts/build_release.py` and an explicit allowlist, never `git archive`
  of an unreviewed private workspace.

English and Simplified Chinese docs should describe the same capabilities and
limitations. Keep media examples anonymous or clearly licensed.
