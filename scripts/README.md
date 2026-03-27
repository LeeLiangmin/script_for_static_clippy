# Scripts

## build_clippy_static.py

静态链接 `rustc_driver` 编译 Clippy，生成独立可执行文件。

### 原理

脚本临时 patch 两处源码，编译后自动还原：

| Patch | 文件 | 变更 | 作用 |
|-------|------|------|------|
| 1 | `compiler/rustc_driver/Cargo.toml` | `["dylib"]` → `["dylib", "rlib"]` | 同时产出动态库和静态库 |
| 2 | `bootstrap compile.rs` | `rlib_only_metadata: true` → `false` | 保留所有 `.rlib` 到 sysroot |

两处缺一不可：patch 1 让 cargo 产出 `.rlib`，patch 2 让 bootstrap 不过滤掉它们。

### 用法

```bash
python scripts/build_clippy_static.py              # 完整流程
python scripts/build_clippy_static.py --keep-stage 2  # 增量编译
python scripts/build_clippy_static.py --patch-only  # 仅 patch，不编译
python scripts/build_clippy_static.py --revert      # 还原 patch
python scripts/build_clippy_static.py --dry-run     # 仅打印操作
```

### justfile 快捷命令

```bash
just clippy-static       # 完整流程
just clippy-static-fast  # --keep-stage 2
just clippy-static-patch # 仅 patch
just clippy-static-revert # 还原
```

### 选项

| 选项 | 说明 |
|-------|------|
| `--stage N` | bootstrap stage（默认 2） |
| `--keep-stage N` | 保留已编译 stage |
| `--native-static` | 静态链接原生依赖（zlib 等） |
| `-v` | 详细输出 |
| `-j N` | 并行任务数 |
| `--output-dir DIR` | 复制产物到指定目录 |
| `--no-verify` | 跳过链接验证 |
| `--no-revert` | 不自动还原 patch |


## 总结
这个 clippy “静态编译”脚本核心是：把 rustc_driver 从动态依赖改成可静态链接进 clippy-driver，然后打包一个可独立用的 cargo-clippy。

按你仓库里的 scripts/build_clippy_static.py，流程是：

修改 compiler/rustc_driver/Cargo.toml
把 crate-type = ["dylib"] 改成 ["dylib", "rlib"]
目的：让 rustc_driver 同时产出 rlib，给静态链接用

修改 src/bootstrap/src/core/build_steps/compile.rs
把“只保留 rustc_driver 和 rmeta”的逻辑关掉（true -> false）
目的：让 sysroot 保留更多 .rlib，否则静态链接时缺库
调 x.py build --stage N src/tools/clippy 编译 Clippy
编译后自动还原补丁（除非 --no-revert）

可选验证：检查 clippy-driver 是否还动态依赖 rustc_driver（Win 用 dumpbin /dependents）
可选打包输出目录（--output-dir）
复制 clippy-driver、cargo-clippy
复制一个“迷你 sysroot”到 lib/rustlib/<host>/lib，用于独立运行
另外从 justfile 看，你的命令入口是：

just clippy-static
just clippy-static-fast（带 --keep-stage 2 --output-dir scripts/output）
just clippy-static-patch / just clippy-static-revert

一句话总结：
这不是“整个 Clippy 全静态到无外部依赖”，而是重点消除对 rustc_driver.dll/so 的动态依赖，并通过补丁 + bootstrap + 打包 sysroot 让 cargo-clippy 更独立可运行。
