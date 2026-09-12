# Intel dependency maintenance

Attention's Python 3.12 installer uses precompiled, SHA-256-verified wheels only.
The MCP SDK indirectly requires `cryptography`. Upstream stopped publishing
[Intel Mac wheels in version 49](https://cryptography.io/en/stable/changelog/#v49-0-0),
so Attention includes an Intel wheel built from the same current version as its
locked dependency. We maintain this Intel build; it is not an upstream wheel.

The wheel lives in `packaging/wheels/` and is copied into both client packages.
Intel Python selects it automatically. Apple Silicon uses the compatible PyPI
wheel. Users do not need Rust, Xcode, or Homebrew OpenSSL. There is no compile
fallback during plugin installation.

## Build and review

`packaging/intel-wheel-sources.json` pins the cryptography and OpenSSL source
archives by version, URL, and SHA-256. Cryptography must match `uv.lock`.
`packaging/intel-wheel-build-requirements.txt` pins the wheel-building tools and
their hashes; these are maintainer dependencies, not plugin dependencies.
Cryptography's Cargo lockfile pins its Rust dependencies.

Run **Build Intel dependency** in GitHub Actions, or on an Intel Mac with Xcode
26+, Rust, Perl, make, and uv:

```sh
uv run --no-config --no-project --isolated --managed-python --python 3.12 python scripts/build_intel_wheel.py --output .build/intel-wheel
```

The builder verifies source hashes before unpacking, statically links OpenSSL,
and targets macOS 14.2. It checks each extension's architecture, minimum system
version, and dynamic dependencies, then runs an encryption round trip. Only
macOS system libraries may remain dynamically linked. The wheel's own Mach-O
install name is an identity, not a dependency.

The output includes the wheel, OpenSSL's license, and `manifest.json` recording
source hashes, wheel hash, toolchain, recipe hash, and CI provenance. The wheel
also includes cryptography's upstream licenses. Review the originating commit
and successful build before replacing `packaging/wheels/` with the output.
These hashes record integrity; they are not a publisher signature or a promise
of bit-for-bit reproducibility across toolchains.

## Update packages

After replacing the reviewed wheel, regenerate dependency hashes:

```sh
uv run --no-sync python scripts/export_requirements.py
uv run --no-sync python scripts/export_requirements.py --check
```

The exporter preserves upstream hashes and adds the bundled wheel's exact hash.
It rejects a modified wheel or a mismatch with the locked cryptography version.
Then rebuild both marketplace packages following the root README. Commit the
sources, provenance, wheel, exported requirements, and regenerated packages
together. Keep the bundled OpenSSL and cryptography current with security fixes.

The normal macOS CI performs binary-only installation and runs the full suite on
Apple Silicon and Intel. Integration tests launch the actual generated MCP and
hook entry points in disposable directories. macOS 14.2 is checked as a binary
deployment target; actual runner execution uses macOS 15. CI does not establish
speaker quality or permission behavior on every physical Intel Mac.
