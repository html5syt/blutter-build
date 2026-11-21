# blutter-build

用 GitHub Actions 编译 blutter（Dart AOT 逆向工具），分析目标 APK 的 `libapp.so`。

## 自动探测

CI 会读取 `libflutter.so` 中的 Dart 版本，以及 `libapp.so` 快照的版本哈希、平台和压缩指针标记，再编译对应 Dart VM 与 blutter。**目录名不参与版本判断**，可以按应用名或发布版本任意命名。

Push 到 `main` 或手动运行 **Build & Analyze with blutter** 时，会自动扫描 `targets/` 中的全部目标，不需要修改 workflow 的 matrix。

```text
targets/
  <target_name>/lib/arm64-v8a/
    libapp.so
    libflutter.so
```

两份 `.so` 必须来自同一个 APK、同一个 ABI；缺失文件或错误目标名会尽早报错。

## 使用

1. 将目标的 `libapp.so` 与 `libflutter.so` 放入上述目录并 push 到 `main`。
2. 或在 Actions 中手动运行：
   - **Build & Analyze with blutter**：自动发现并分析全部目标。
   - **Analyze libapp with blutter**：填写 `target`，自动探测 Dart 版本并分析该目标。
   - **Build blutter dartvm (auto or by version)**：只编译，不分析。填写 `target`，保留 `dart_version=auto` 即自动探测；也可以直接填写 `dart_version=3.14.0` 等版本，此时不需要目标文件。
3. 下载产物：
   - `blutter-out-<target>`：`pp.txt`、`objs.txt`、`asm/`、`blutter_frida.js` 和 `dart-info.json`。
   - `blutter-bin-<target>-dart<version>`：该目标对应的 `bin/`、Dart VM 库与头文件。
   - 仅编译 workflow：`blutter-bin-dart<version>`，并附带探测/构建元数据。

首次构建会下载对应 Dart SDK 源码并编译，通常需要 15–40 分钟；workflow 的超时为 300 分钟。上传 artifact 不等于自动缓存，后续 CI 仍会重新构建。

## Dart 3.14 兼容性

当前目标实测是 Dart **3.14.0**。该版本把旧 VM/Isolate 四组快照符号改为 `_kDartSnapshotData` / `_kDartSnapshotText`，同时更改 VM 初始化 API、stub 列表和闭包布局。上游 blutter 尚未全部兼容，原流程会在查找 `_kDartVmSnapshotData` 时抛出 `TypeError`。

仓库固定上游 revision，并在每次 CI checkout 后应用 `patches/blutter-dart314.patch`，同时兼容旧快照符号与新统一快照。Dart 3.14+ 自动启用 **no-analysis**：仍生成对象、对象池、汇编和 Frida 模板，但不运行尚不兼容的高级代码模式分析器（例如参数/闭包模式识别）。Frida 模板不会输出已失效的固定闭包 context 偏移。旧 Dart 版本保留原来的分析模式。未来 Dart 版本仍需重新验证，自动探测不代表无限向后兼容。

共享构建脚本调用上游 API，不再维护一份易失同步的兼容宏副本。更新上游时需一起更新 `scripts/blutter_ci.py` 中的 revision、检查补丁并运行回归测试。

## 本地使用与验证

Linux 依赖：`git cmake ninja-build build-essential pkg-config libicu-dev libcapstone-dev python3-pyelftools python3-requests`。需要支持 C++20 的较新编译器（推荐 GCC 13+）。CI 固定使用 Ubuntu 24.04。

```bash
# 固定上游版本，与 CI 一致
REVISION=$(python3 -c "import sys; sys.path.insert(0, 'scripts'); from blutter_ci import UPSTREAM_REVISION; print(UPSTREAM_REVISION)")
git clone https://github.com/worawit/blutter.git
git -C blutter checkout "$REVISION"
python3 scripts/blutter_ci.py patch

python3 scripts/blutter_ci.py discover
python3 scripts/blutter_ci.py detect --target <target_name>
python3 scripts/blutter_ci.py analyze --target <target_name>
python3 scripts/blutter_ci.py build --target <target_name>
python3 scripts/blutter_ci.py build --dart-version 3.14.0
python3 -m unittest discover -s tests -v
```

## 从 APK 提取目标库

```bash
unzip -o 原版.apk -d /tmp/x 'lib/arm64-v8a/libapp.so' 'lib/arm64-v8a/libflutter.so'
```

仅用于自有/授权分析；不要提交未授权或含敏感信息的 APK / `.so`。`libapp.so` 本身含应用业务代码。

## 本次运行时修复与验证

最新一次 CI 的编译已经成功，失败发生在 `DartTypes.cpp` 的类型读取阶段。当前目标的 AOT 快照含被优化掉的类型元数据（Dart Null，class id 173），原代码会直接 abort。补丁现在将其明确标为 `<optimized-out>`；真正未知的非类型对象仍然报错，并返回非零退出码。

对于已优化掉或丢弃 Code 对象的函数，补丁只接受落在实际映射范围内的入口地址。不读取无效代码缓冲区；保留有效名称/地址，缺失函数长度时由 IDA 推断边界。`no-analysis` 下恢复了基础 ARM64 指令转储，但不会运行高级指令模式分析。

CI 还会检查对象转储、IDA 脚本、Frida 模板和函数目录是否完整；失败时上传 `blutter-debug-*` 日志，不会仅凭 `dart-info.json` 就宣称分析成功。编译后运行真实 Dart VM 的原生回归测试，而不是只做 C++ 语法检查。

当前 Windows 环境已经完成整个目标的实际分析。最近一次产物在 `out/quick-check/`，包含约 1.1 万条 IDA 命名记录（含特殊入口和 stub，不等于同样数量的独立函数）。同版本复用构建实测约 14 秒，耗时随目标和磁盘而变化。没有重新 clone 或编译 Dart SDK。

## Windows 本地快速分析：无需重新编译

在仓库根目录打开 PowerShell。当前已编译好的程序为：

```text
blutter/bin/blutter_dartvm3.14.0_android_arm64_no-analysis.exe
```

### 推荐：自动识别版本，强制复用已有程序

```powershell
Set-Location D:\Projects\Reverse\blutter-build
uv run --no-project --with pyelftools --with requests python scripts/blutter_ci.py analyze --target yunhu_dart3140 --no-build --out-dir out/yunhu-local --output-json out/yunhu-local/dart-info.json
```

`--no-build` 保证不会下载 Dart SDK 或调用 CMake/Ninja。找不到匹配的程序时会报错，不会悄悄开始数十分钟构建。Python 依赖由当前已安装的 uv 缓存复用；首次解析依赖仍可能需要联网。

分析其他同版本目标时，将同一 APK 的两份 `.so` 放入 `targets/<name>/lib/arm64-v8a/`，再替换 `--target <name>` 与输出目录。

### 最直接：跳过 Python，直接调用已经编译好的程序

已确认输入是 Dart 3.14.0、Android arm64、压缩指针快照时，可以直接运行：

```powershell
New-Item -ItemType Directory -Force out/yunhu-direct | Out-Null
& .\blutter\bin\blutter_dartvm3.14.0_android_arm64_no-analysis.exe -i .\targets\yunhu_dart3140\lib\arm64-v8a\libapp.so -o .\out\yunhu-direct
```

这条命令不需要 Python、uv、CMake 或 Visual Studio 开发者环境，也不会自动探测版本。必须使用匹配的程序。请保留 `blutter/bin/` 里的 `capstone.dll`、`icuuc73.dll`、`icudt73.dll`；生成 Frida 模板还会读取仓库中的 `blutter/scripts/frida.template.js`，不要只移动一个 `.exe` 后删除原 checkout。

输出中：

- `asm/`：库、类、函数与可读取的 ARM64 指令；丢弃了 Code/长度信息的函数可能只有声明。
- `pp.txt`、`objs.txt`：对象池及对象内容。
- `ida_script/addNames.py`、`ida_dart_struct.h`：IDA 名称、函数及结构导入资料。
- `blutter_frida.js`：Frida 模板。

用 IDA 打开同一份 `libapp.so` 后可导入 `addNames.py`。默认地址按模块基址 0 生成；重定位过的 IDB 需要修正偏移。上游脚本仍包含旧 `ida_struct` API，IDA 9.x 需要另行适配。被混淆、优化或裁剪掉的原始名称/类型不能凭空恢复；这些结果也不是完整的原始 Dart 源码。

### 首次遇到新的 Dart 版本

去掉 `--no-build` 可使用自动构建流程。Windows 下需要在 x64 Visual Studio 开发者命令环境中运行，并为新版本编译启用当前 MSVC 的 UTF-8 与标准预处理器：

```powershell
$env:_CL_ = '/Zc:preprocessor /utf-8'
uv run --no-project --with pyelftools --with requests python scripts/blutter_ci.py build --target <name>
```

只有这一步才需要编译器及 ICU/Capstone 开发库；已有匹配程序的日常分析不需要开发者环境。Linux CI 产物是 Linux 可执行文件，不能直接在 Windows 上运行，需使用 WSL/Linux 或本地 Windows 构建。

## 回归检查

```powershell
uv run --no-project --with pyelftools --with requests python -m unittest discover -s tests -v
# 下列原生测试需要已编译的 Dart VM；Windows 下在 x64 开发者命令环境运行
uv run --no-project --with pyelftools --with requests python scripts/test_native_types.py --target yunhu_dart3140
```
