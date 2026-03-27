"""读取 rlib/dll 中嵌入的 rustc metadata 元信息

metadata 布局 (参考 compiler/rustc_metadata/src/rmeta/mod.rs):
  METADATA_HEADER (8 bytes): b"rust\\x00\\x00\\x00\\x0a"  (METADATA_VERSION=10)
  root_pos        (8 bytes): u64 LE, CrateRoot 在 blob 中的位置
  version_string           : 紧跟在 header+root_pos 之后, MemDecoder 编码的 String
                             (LEB128 长度 + UTF-8 字节)

rlib 是 ar 归档, metadata 在 lib.rmeta 成员中.
dll 的 metadata 嵌入在 PE 的 .rustc section 中.
"""
import struct
import sys
from pathlib import Path

METADATA_HEADER = b"rust\x00\x00\x00\x0a"  # METADATA_VERSION = 10


def read_leb128(data: bytes, offset: int) -> tuple[int, int]:
    """读取 unsigned LEB128, 返回 (value, new_offset)"""
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, offset


def decode_version_from_blob(blob: bytes) -> str | None:
    """从 metadata blob 中解码版本字符串。

    版本字符串是 blob 中第一个编码的值 (LazyValue<String>),
    位于 HEADER(8) + root_pos(8) = 偏移 16 处。
    编码方式: LEB128(字符串长度) + UTF-8 字节。
    """
    if len(blob) < 17:
        return None
    # root_pos
    root_pos = struct.unpack_from("<Q", blob, 8)[0]
    # 版本字符串在偏移 16 处 (紧跟 root_pos 之后)
    str_len, str_start = read_leb128(blob, 16)
    if str_len <= 0 or str_start + str_len > len(blob):
        return None
    try:
        return blob[str_start:str_start + str_len].decode("utf-8")
    except UnicodeDecodeError:
        return None


def find_all_rustc_strings(data: bytes) -> set[str]:
    """搜索所有 'rustc ' 明文版本字符串 (用于 DLL)"""
    versions = set()
    pos = 0
    while True:
        pos = data.find(b"rustc ", pos)
        if pos < 0:
            break
        ver = data[pos:pos + 100]
        end = len(ver)
        for i, b in enumerate(ver):
            if b < 32 or b > 126:
                end = i
                break
        v = ver[:end].decode("ascii", errors="replace")
        if len(v) > 8:
            versions.add(v)
        pos += 1
    return versions


def analyze_file(filepath: Path):
    print(f"\n{'='*60}")
    print(f"文件: {filepath.name}")
    print(f"大小: {filepath.stat().st_size / 1024:.1f} KB")

    data = filepath.read_bytes()

    # 查找 metadata header
    idx = data.find(METADATA_HEADER)
    if idx < 0:
        print("未找到 metadata header")
        return

    print(f"Metadata header: 偏移 {idx} (0x{idx:x})")
    print(f"METADATA_VERSION: {data[idx+7]}")

    # root_pos
    if len(data) > idx + 16:
        root_pos = struct.unpack_from("<Q", data, idx + 8)[0]
        print(f"CrateRoot 位置: {root_pos}")

    # 提取 metadata blob (从 header 开始)
    # 对于 DLL, header 后面有 data_length 字段
    # 对于 rlib, metadata 就是 .rmeta 成员的内容
    blob = data[idx:]

    # 方法 1: MemDecoder 解码
    ver = decode_version_from_blob(blob)
    if ver:
        print(f"编译器版本 (decoded): {ver}")
    else:
        # 方法 2: 明文搜索 (DLL 中 metadata 有时未编码)
        versions = find_all_rustc_strings(data[idx:])
        if versions:
            for v in sorted(versions):
                print(f"编译器版本 (search): {v}")
        else:
            print("编译器版本: 无法解码")

    # PE DLL 额外信息
    if filepath.suffix == ".dll" and data[:2] == b"MZ":
        print(f"PE 格式: 是")


def main():
    if len(sys.argv) > 1:
        lib_dir = Path(sys.argv[1])
    else:
        lib_dir = Path(r"D:\lee_space\rust\build\x86_64-pc-windows-msvc\stage0\lib\rustlib\x86_64-pc-windows-msvc\lib")

    print(f"目录: {lib_dir}")

    # 分析 std 相关文件
    for pattern in ["libstd-*.rlib", "std-*.dll", "std-*.dll.lib"]:
        for f in sorted(lib_dir.glob(pattern)):
            analyze_file(f)

    # 也看一下其他关键 crate
    print(f"\n{'='*60}")
    print("其他关键 crate 版本:")
    for pattern in ["libcore-*.rlib", "liballoc-*.rlib", "librustc_demangle-*.rlib"]:
        for f in sorted(lib_dir.glob(pattern)):
            idx = f.read_bytes().find(METADATA_HEADER)
            if idx >= 0:
                blob = f.read_bytes()[idx:]
                ver = decode_version_from_blob(blob)
                print(f"  {f.stem:45s} {ver or 'unknown'}")


if __name__ == "__main__":
    main()
