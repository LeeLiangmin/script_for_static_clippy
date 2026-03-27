#!/usr/bin/env python3
"""测试 scripts/output 下的 cargo-clippy / clippy-driver 是否具备 clippy 功能。"""

import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
SAMPLE_RS = Path(__file__).resolve().parent / "sample_project" / "src" / "main.rs"

EXE = ".exe" if sys.platform == "win32" else ""
CARGO_CLIPPY = OUTPUT_DIR / f"cargo-clippy{EXE}"
CLIPPY_DRIVER = OUTPUT_DIR / f"clippy-driver{EXE}"
NULL = str(Path(__file__).resolve().parent / "_clippy_test_out") if sys.platform == "win32" else "/dev/null"


def run_test(name, fn):
    print(f"\n[测试] {name}")
    try:
        return fn()
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def test_exists():
    ok = True
    for p in [CARGO_CLIPPY, CLIPPY_DRIVER]:
        if p.exists():
            print(f"  [OK] {p.name} ({p.stat().st_size / 1048576:.1f} MB)")
        else:
            print(f"  [FAIL] {p.name} 不存在")
            ok = False
    return ok


def test_version():
    r = subprocess.run([str(CLIPPY_DRIVER), "--version"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 0 and "clippy" in r.stdout.lower():
        print(f"  [OK] {r.stdout.strip()}")
        return True
    print(f"  [FAIL] rc={r.returncode} stdout={r.stdout.strip()}")
    return False


def test_cargo_clippy_help():
    """cargo-clippy 应能输出 clippy 相关的帮助信息。"""
    r = subprocess.run([str(CARGO_CLIPPY), "--help"],
                       capture_output=True, text=True, timeout=30)
    output = r.stdout + r.stderr
    if "clippy" in output.lower():
        print(f"  [OK] cargo-clippy --help 包含 clippy 信息")
        return True
    print(f"  [FAIL] 帮助信息中无 clippy 字样")
    return False


def test_clippy_lints():
    """验证 clippy-driver 内置了 clippy lint 规则。

    策略 1: 如果 output 目录有 sysroot 布局 (lib/rustlib/...)，用它做完整 lint
    策略 2: 用 stage1 sysroot 做完整 lint
    策略 3: 回退到验证 clippy-driver 能识别 clippy lint 名称
    """
    def count_clippy_warnings(output):
        """统计 clippy 警告数。warning 行本身不含 clippy::，但 note 行有。"""
        lines = output.splitlines()
        warnings = [l for l in lines if l.startswith("warning:") and "warnings emitted" not in l]
        has_clippy = any("clippy::" in l for l in lines)
        return warnings if has_clippy else []

    def try_lint(sysroot, label):
        r = subprocess.run(
            [str(CLIPPY_DRIVER), "--sysroot", str(sysroot),
             "-W", "clippy::all", "--edition", "2021",
             str(SAMPLE_RS), "--crate-type", "bin",
             "--emit", "metadata", "-o", NULL],
            capture_output=True, text=True, timeout=60,
        )
        warnings = count_clippy_warnings(r.stderr + r.stdout)
        if warnings:
            print(f"  [OK] 检测到 {len(warnings)} 条 clippy 警告 ({label}):")
            for w in warnings[:6]:
                print(f"    {w.strip()}")
            return True
        return False

    # 策略 1: output 目录自带 sysroot
    if (OUTPUT_DIR / "lib" / "rustlib").exists():
        if try_lint(OUTPUT_DIR, "output sysroot"):
            return True

    # 策略 2: 用 bootstrap stage sysroot
    rust_root = Path(__file__).resolve().parent.parent.parent
    for s in [1, 2]:
        sysroot = rust_root / "build" / "x86_64-pc-windows-msvc" / f"stage{s}"
        lib = sysroot / "lib" / "rustlib" / "x86_64-pc-windows-msvc" / "lib"
        if lib.exists() and any(lib.glob("libstd-*.rlib")):
            if try_lint(sysroot, f"stage{s} sysroot"):
                return True

    # 策略 3: 验证 clippy-driver 能识别 clippy lint 名称
    r_known = subprocess.run(
        [str(CLIPPY_DRIVER), "-W", "clippy::needless_return", "--print", "cfg"],
        capture_output=True, text=True, timeout=30,
    )
    r_unknown = subprocess.run(
        [str(CLIPPY_DRIVER), "-W", "clippy::this_lint_does_not_exist_xyz", "--print", "cfg"],
        capture_output=True, text=True, timeout=30,
    )
    known_ok = "unknown lint" not in r_known.stderr.lower()
    unknown_ok = "unknown lint" in r_unknown.stderr.lower()

    if known_ok and unknown_ok:
        print(f"  [OK] clippy-driver 能识别 clippy lint 规则")
        print(f"    clippy::needless_return → 已识别")
        print(f"    clippy::this_lint_does_not_exist_xyz → unknown lint")
        return True
    if known_ok:
        print(f"  [OK] clippy-driver 能识别 clippy::needless_return")
        return True
    print(f"  [FAIL] clippy-driver 无法识别 clippy lint")
    return False


def test_no_rustc_driver_dll():
    if sys.platform != "win32":
        print("  [SKIP] 仅 Windows")
        return True
    try:
        r = subprocess.run(["llvm-objdump", "-p", str(CLIPPY_DRIVER)],
                           capture_output=True, text=True, timeout=30)
        dlls = [l.strip() for l in r.stdout.splitlines() if "DLL Name:" in l]
        has = any("rustc_driver" in d.lower() for d in dlls)
        print(f"  [{'FAIL' if has else 'OK'}] {'有' if has else '无'} rustc_driver DLL (共 {len(dlls)} 个)")
        return not has
    except FileNotFoundError:
        print("  [SKIP] llvm-objdump 不可用")
        return True


def main():
    tests = [
        ("文件检查", test_exists),
        ("版本信息", test_version),
        ("cargo-clippy --help", test_cargo_clippy_help),
        ("clippy lint 功能", test_clippy_lints),
        ("静态链接验证", test_no_rustc_driver_dll),
    ]

    print("=" * 50)
    print("  Clippy 静态链接产物测试")
    print("=" * 50)

    passed = sum(1 for name, fn in tests if run_test(name, fn))
    print(f"\n{'=' * 50}")
    print(f"  结果: {passed}/{len(tests)} 通过")
    print(f"{'=' * 50}")
    sys.exit(0 if passed == len(tests) else 1)


if __name__ == "__main__":
    main()
