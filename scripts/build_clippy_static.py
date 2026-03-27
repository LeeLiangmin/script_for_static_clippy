#!/usr/bin/env python3
"""
build_clippy_static.py — 静态链接 rustc_driver 编译 Clippy

原理：
  1. rustc_driver crate-type: ["dylib"] → ["dylib", "rlib"]  (同时产出动态/静态库)
  2. bootstrap compile.rs: rlib_only_metadata: true → false    (保留所有 .rlib 到 sysroot)
  3. 通过 ./x build 编译 Clippy
  4. 编译后自动还原上述修改

用法：
  python scripts/build_clippy_static.py [--keep-stage 2] [--patch-only] [--revert]
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────

RUST_ROOT = Path(__file__).resolve().parent.parent

RUSTC_DRIVER_TOML = RUST_ROOT / "compiler" / "rustc_driver" / "Cargo.toml"
COMPILE_RS = RUST_ROOT / "src" / "bootstrap" / "src" / "core" / "build_steps" / "compile.rs"

# patch 定义: (文件, 原始文本, 替换文本)
PATCHES = [
    (
        RUSTC_DRIVER_TOML,
        'crate-type = ["dylib"]',
        'crate-type = ["dylib", "rlib"]',
    ),
    (
        COMPILE_RS,
        "true, // Only ship rustc_driver.so and .rmeta files, not all intermediate .rlib files.",
        "false, // [PATCHED] Ship all .rlib files for static linking.",
    ),
]

IS_WIN = platform.system() == "Windows"
EXE = ".exe" if IS_WIN else ""


# ── patch / revert ────────────────────────────────────────

def apply_patches(dry_run=False) -> list[bool]:
    """应用所有 patch，返回每个 patch 是否实际修改了文件。"""
    applied = []
    for path, old, new in PATCHES:
        content = path.read_text(encoding="utf-8")
        if new in content:
            print(f"  [跳过] {path.name}: 已是目标状态")
            applied.append(False)
        elif old not in content:
            print(f"  [警告] {path.name}: 未找到预期文本，跳过", file=sys.stderr)
            applied.append(False)
        else:
            print(f"  [修改] {path.name}")
            if not dry_run:
                path.write_text(content.replace(old, new, 1), encoding="utf-8")
            applied.append(True)
    return applied


def revert_patches(applied=None):
    """还原 patch。applied 为 None 时尝试还原所有。"""
    for i, (path, old, new) in enumerate(PATCHES):
        if applied is not None and not applied[i]:
            continue
        content = path.read_text(encoding="utf-8")
        if new in content:
            path.write_text(content.replace(new, old, 1), encoding="utf-8")
            print(f"  [还原] {path.name}")


# ── 编译 ──────────────────────────────────────────────────

def build_clippy(stage, keep_stage=None, jobs=None, verbose=False, native_static=False):
    """通过 bootstrap 编译 Clippy。"""
    cmd = [sys.executable, "x.py", "build", "--stage", str(stage), "src/tools/clippy"]
    if keep_stage is not None:
        cmd += ["--keep-stage", str(keep_stage)]
    if verbose:
        cmd.append("-v")
    if jobs:
        cmd += ["-j", str(jobs)]

    env = os.environ.copy()
    if native_static:
        env["LIBZ_SYS_STATIC"] = "1"

    print(f"\n  $ {' '.join(cmd)}\n")
    return subprocess.run(cmd, env=env, cwd=str(RUST_ROOT)).returncode == 0


# ── 产物查找与验证 ────────────────────────────────────────

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


def find_binaries(stage) -> list[Path]:
    host = detect_host()
    names = [f"clippy-driver{EXE}", f"cargo-clippy{EXE}"]
    for d in [
        RUST_ROOT / "build" / host / f"stage{stage}-tools-bin",
        RUST_ROOT / "build" / host / f"stage{stage}" / "bin",
    ]:
        found = [d / n for n in names if (d / n).exists()]
        if found:
            return found
    return []


def find_sysroot_libs(stage) -> Path | None:
    """找到包含 std rlib 的 sysroot lib 目录。"""
    host = detect_host()
    # bootstrap 编译后 std 在 stage{N}/lib/rustlib/<target>/lib/ 或 stage{N-1}
    for s in [stage, stage - 1]:
        lib_dir = RUST_ROOT / "build" / host / f"stage{s}" / "lib" / "rustlib" / host / "lib"
        if lib_dir.exists() and any(lib_dir.glob("libstd-*.rlib")):
            return lib_dir
    return None


def copy_with_sysroot(binaries: list[Path], output_dir: Path, stage: int):
    """复制产物并组装迷你 sysroot，使 cargo-clippy 可独立运行。

    输出布局:
      output_dir/
        bin/clippy-driver.exe
        bin/cargo-clippy.exe
        lib/rustlib/<target>/lib/libstd-xxx.rlib ...
    """
    host = detect_host()
    bin_dir = output_dir / "bin"
    lib_dir = output_dir / "lib" / "rustlib" / host / "lib"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    # 复制二进制
    for b in binaries:
        shutil.copy2(b, bin_dir / b.name)
        print(f"  {b.name} → {bin_dir}")

    # 复制 std 相关库
    src_lib = find_sysroot_libs(stage)
    if not src_lib:
        print("  [警告] 未找到 std 库，cargo-clippy 可能无法独立运行", file=sys.stderr)
        return

    # 复制 rlib 和 std 动态库，跳过编译器 crate（librustc_* 除 demangle/std_workspace）
    # 这些编译器 crate 已经静态链接进 clippy-driver，不需要在 sysroot 中
    STD_RUSTC_KEEP = ("librustc_demangle", "librustc_std_workspace")
    copied = 0
    for f in src_lib.iterdir():
        if f.suffix == ".rlib" or (f.name.startswith("std-") and f.suffix in (".dll", ".lib")):
            if f.stem.startswith("librustc_") and not any(f.stem.startswith(p) for p in STD_RUSTC_KEEP):
                continue
            shutil.copy2(f, lib_dir / f.name)
            copied += 1
    print(f"  复制 {copied} 个库文件 → {lib_dir}")


def verify_static(binary: Path) -> tuple[bool, str]:
    """检查是否动态链接了 rustc_driver。返回 (is_static, detail)。"""
    try:
        if IS_WIN:
            p = subprocess.run(["dumpbin", "/dependents", str(binary)],
                               capture_output=True, text=True, timeout=30)
        elif platform.system() == "Linux":
            p = subprocess.run(["ldd", str(binary)],
                               capture_output=True, text=True, timeout=30)
        elif platform.system() == "Darwin":
            p = subprocess.run(["otool", "-L", str(binary)],
                               capture_output=True, text=True, timeout=30)
        else:
            return False, "不支持的平台"
        has_dyn = "rustc_driver" in p.stdout.lower()
        return (not has_dyn, "动态链接 rustc_driver" if has_dyn else "静态链接")
    except FileNotFoundError:
        return False, "验证工具不可用"
    except Exception as e:
        return False, f"验证出错: {e}"


# ── 主流程 ────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="静态链接 rustc_driver 编译 Clippy")
    p.add_argument("--stage", type=int, default=2)
    p.add_argument("--keep-stage", type=int, default=None)
    p.add_argument("--native-static", action="store_true", help="静态链接原生依赖")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-j", "--jobs", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="仅打印操作")
    p.add_argument("--output-dir", help="复制产物到指定目录")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--no-revert", action="store_true")
    p.add_argument("--patch-only", action="store_true", help="仅 patch 源码，不编译")
    p.add_argument("--revert", action="store_true", help="还原所有 patch")
    args = p.parse_args()

    # revert 模式
    if args.revert:
        print("还原 patch...")
        revert_patches()
        return

    # 1. patch
    print("应用 patch...")
    applied = apply_patches(args.dry_run)

    if args.patch_only:
        print("patch 完成（--patch-only，跳过编译）。用 --revert 还原。")
        return

    # 2. 编译
    print(f"编译 Clippy (stage {args.stage})...")
    try:
        ok = not args.dry_run and build_clippy(
            args.stage, args.keep_stage, args.jobs, args.verbose, args.native_static,
        )
        if args.dry_run:
            print("[dry-run] 跳过编译")
            return
    except KeyboardInterrupt:
        ok = False
        print("\n编译被中断")
    finally:
        # 3. 还原
        if any(applied) and not args.no_revert:
            print("还原 patch...")
            revert_patches(applied)

    if not ok:
        sys.exit(1)

    # 4. 产物
    binaries = find_binaries(args.stage)
    if binaries:
        print("\n产物:")
        for b in binaries:
            print(f"  {b}  ({b.stat().st_size / 1048576:.1f} MB)")
    else:
        print("警告：未找到产物", file=sys.stderr)

    if not args.no_verify and binaries:
        print("\n验证:")
        for b in binaries:
            is_static, detail = verify_static(b)
            print(f"  [{'OK' if is_static else 'FAIL'}] {b.name}: {detail}")

    if args.output_dir and binaries:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        print("\n复制产物（含 sysroot）:")
        copy_with_sysroot(binaries, out, args.stage)

    print("\n完成！")


if __name__ == "__main__":
    main()
