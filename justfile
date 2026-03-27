EXE := if os() == "windows" { ".exe" } else { "" }

# ── bootstrap 构建 ────────────────────────────────────────
dev:
    ./x build --stage 2 --dry-run

prod:
    ./x build --stage 2

verify:
    ./x build --stage 3 --keep-stage 2

# ── Clippy 静态链接 ──────────────────────────────────────
clippy-static:
    python scripts/build_clippy_static.py

clippy-static-fast:
    python scripts/build_clippy_static.py --keep-stage 2 --output-dir scripts/output

clippy-static-patch:
    python scripts/build_clippy_static.py --patch-only

clippy-static-revert:
    python scripts/build_clippy_static.py --revert

# 用 output 中的独立 cargo-clippy 检查 test/sample_project
clippy-test:
    scripts/output/bin/cargo-clippy{{EXE}} clippy --manifest-path scripts/test/sample_project/Cargo.toml -- -W clippy::all
