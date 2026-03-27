#!/usr/bin/env python3
"""
pack_clippy.py — 将已编译的 clippy 产物 + sysroot 打包到 output 目录

用法：
  python scripts/pack_clippy.py [--output-dir scripts/output]

输出布局：
  output/
    bin/clippy-driver.exe
    bin/cargo-clippy.exe
    lib/rustlib/<target>/lib/*.rlib
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

RUST_ROOT = Path(__file__).resolve().parent.parent
IS_WIN = platform.system() == "Windows"
EXE = ".exe" if IS_WIN else ""


def detect_host() -> str:
    try:
        out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    m = platform.machine().lower()
    s = platform.system().lower()
    if s == "windows":
        return "x86_64-pc-windows-msvc" if m == "amd64" else f"{m}-pc-windows-msvc"
    if s == "linux":
        return f"{m}-unknown-linux-gnu"
    if s == "darwin":
        return f"{m}-apple-darwin"
    return f"{m}-unknown-{s}"


def find_binaries(host) -> list[Path]:
    names = [f"clippy-driver{EXE}", f"cargo-clippy{EXE}"]
    for d in [
        RUST_ROOT / "build" / host / "stage2-tools-bin",
        RUST_ROOT / "build" / host / "stage2" / "bin",
    ]:
        found = [d / n for n in names if (d / n).exists()]
        if found:
            return found
    return []


def find_sysroot_libs(host) -> Path | None:
    for s in [2, 1]:
        lib_dir = RUST_ROOT / "build" / host / f"stage{s}" / "lib" / "rustlib" / host / "lib"
        if lib_dir.exists() and any(lib_dir.glob("libstd-*.rlib")):
            return lib_dir
    return None


def main():
    p = argparse.ArgumentParser(description="打包 clippy 产物 + sysroot")
    p.add_argument("--output-dir", default="scripts/output", help="输出目录")
    args = p.parse_args()

    host = detect_host()
    print(f"Host: {host}")

    # 查找二进制
    binaries = find_binaries(host)
    if not binaries:
        print("错误：未找到 clippy 二进制文件，请先运行 just clippy-static", file=sys.stderr)
        sys.exit(1)

    # 查找 sysroot 库
    src_lib = find_sysroot_libs(host)
    if not src_lib:
        print("错误：未找到 sysroot 库", file=sys.stderr)
        sys.exit(1)

    out = Path(args.output_dir)
    if not out.is_absolute():
        out = RUST_ROOT / out

    bin_dir = out / "bin"
    lib_dir = out / "lib" / "rustlib" / host / "lib"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    # 复制二进制
    print("\n二进制:")
    for b in binaries:
        shutil.copy2(b, bin_dir / b.name)
        print(f"  {b.name} ({b.stat().st_size / 1048576:.1f} MB) → {bin_dir}")

    # 复制 rlib + std dll，跳过编译器 crate（已静态链接进 clippy-driver）
    STD_RUSTC_KEEP = ("librustc_demangle", "librustc_std_workspace")
    print(f"\n库文件 (from {src_lib}):")
    copied = 0
    total_size = 0
    for f in sorted(src_lib.iterdir()):
        if f.suffix == ".rlib" or (f.name.startswith("std-") and f.suffix in (".dll", ".lib")):
            if f.stem.startswith("librustc_") and not any(f.stem.startswith(p) for p in STD_RUSTC_KEEP):
                continue
            shutil.copy2(f, lib_dir / f.name)
            copied += 1
            total_size += f.stat().st_size
    print(f"  {copied} 个文件, {total_size / 1048576:.1f} MB")

    # 统计总大小
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\n输出目录: {out}")
    print(f"总大小: {total / 1048576:.1f} MB")
    print(f"\n使用方式:")
    print(f"  {out / 'bin' / f'cargo-clippy{EXE}'} clippy --manifest-path <path/to/Cargo.toml>")
    print(f"  或直接: {out / f'cargo-clippy{EXE}'} clippy --manifest-path <path/to/Cargo.toml>")


if __name__ == "__main__":
    main()
