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
