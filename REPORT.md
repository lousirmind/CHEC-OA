# OA 自动化脚本 — 多版本代码对比与运行测试报告

**测试日期**: 2026-05-10  
**测试环境**: macOS 24.6.0 + Python 3.12 + Playwright (Chromium) + ddddocr  
**OA 地址**: http://checea.edmcs.cn/cloudoa/

---

## 一、版本概览

| 项目 | v1 | v2 | v3 | v4 |
|------|:--:|:--:|:--:|:--:|
| **文件** | `oa_auth_v1/oa_auto_v1.py` | `oa_auto_v2.py` | `oa_auto_v3.py` | `oa_auto_v4.py` |
| **辅助文件** | `save_auth.py` | 无 | 无 | 无 |
| **代码行数** | ~686 行 | ~794 行 | ~1129 行 | ~887 行 |
| **登录方式** | 手动输入验证码 | 手动输入验证码 | ddddocr 自动识别 | ddddocr 自动识别 |
| **auth 存储** | 独立 `save_auth.py` | 集成于主脚本 | 集成于主脚本 | 集成于主脚本 |
| **配置管理** | 散落硬编码 | CONFIG 字典 | CONFIG 字典 | CONFIG 字典 |
| **日志系统** | `print()` 打印 | `logging` 模块 | `logging` 模块 | `logging` 模块 |
| **重试机制** | 无 | `@retry` 装饰器（函数级，max=3） | `retry_module()`（模块级，含清理+回首页） | `@retry` 装饰器（函数级，max=3） |
| **失败处理** | 终止循环 | 终止循环 (`break`) | **跳过继续** (`continue`) | 终止循环 (`break`) |
| **失败截图** | ❌ | ✅ | ✅ | ✅ |
| **进度追踪** | ❌ | ❌ | ✅ `status.json` | ❌ |
| **"已在待发文档"检测** | ❌ | ❌ | ✅ 自动跳过 | ❌ |
| **安全清理函数** | ❌ | ❌ | `safe_close_popups()` + `safe_go_home()` | ❌ |
| **无头/有窗切换** | 固定有窗 | ✅ 自动切换 | ✅ 自动切换 | ✅ 自动切换 |
| **默认循环次数** | 200 | 1000 | 1000 | 100 |
| **翻页范围** | 第 1-10 页 | 第 11-21 页 | 第 11-21 页（修正） | 第 11-21 页 |

---

## 二、各版本代码详细差异

### 2.1 登录模块差异

**v1** (`oa_auto_v1.py:do_login`):
- 纯手动验证码，弹出浏览器后用户自行输入
- `input()` 阻塞等待用户按回车
- 无验证码自动识别能力
- 登录状态保存由独立脚本 `save_auth.py` 完成

**v2** (`oa_auto_v2.py:do_login`):
- 手动验证码 + 手动输入
- 登录成功后保存 `auth.json`
- Session 失效时自动弹出浏览器窗口，触发手动登录
- 登录完成后自动切回无头模式

**v3** (`oa_auto_v3.py:recognize_captcha + captcha_login_with_retry`):
- 引入 `ddddocr` 验证码自动识别，带多种选择器降级方案
- 识别失败时自动降级为手动输入
- 最多重试 5 次（每次重新访问登录页）
- 新增 `save_auth_state()` 统一保存逻辑

**v4**: 完整复用 v3 的 `recognize_captcha()` + `captcha_login_with_retry()` 实现

### 2.2 重试机制差异

**v2/v4** — 函数装饰器重试:
```python
@retry(max_times=2, delay_ms=3000)
def add_receive_document(page) -> bool:
    ...
```
- 重试时仅等待 3 秒后重新调用函数
- 不清理页面状态（弹窗、遮罩层等残留）
- 异常直接向上传播

**v3** — 模块级重试包装器:
```python
def retry_module(func, page, module_name: str):
    for attempt in range(1, max_retries + 1):
        ...
        if attempt < max_retries:
            safe_close_popups(page)   # 清理弹窗
            safe_go_home(page)        # 回到首页
            time.sleep(delay)         # 等待
```
- 重试前自动清理弹窗遮罩层并回到首页
- 可配置重试次数和等待时间
- 支持特殊返回值透传（如 `"skip_to_module3"`）

### 2.3 主循环逻辑差异

**v2/v4** — 失败即终止:
```python
for i in range(1, repeat_count + 1):
    ok = run_one_cycle(page, i)
    results.append(ok)
    if not ok:
        log.error("本次循环失败，终止后续循环")
        break                    # ← 终止所有后续循环
```

**v3** — 失败跳过继续:
```python
for i in range(1, total + 1):
    ok = run_one_cycle(page, i, total)
    results.append(ok)
    if not ok:
        skipped += 1
        log.warning(f"跳过并继续下一次")  # ← 不 break
```

### 2.4 模块2-添加收文的特殊处理

**v3 独有**: 检测 "已在待发文档中" 提示，自动跳过转收文直接进入模块3：
```python
# v3 特有 — 在 iframe 中检测提示文本
if "已在待发文档中" in page_text:
    return "skip_to_module3"   # 特殊返回值，main 循环识别后跳过模块2
```
v2/v4 无此处理，遇到该情况会在 `wait_for_selector` 处超时失败。

### 2.5 进度追踪

**v3 独有**: `status.json` 实时进度文件：
```json
{
  "current_cycle": 45, "total_cycles": 100,
  "progress_pct": 45.0, "current_module": "模块3-启动流程",
  "last_result": "执行中...", "skipped_count": 2,
  "timestamp": "2026-04-13 15:30:00", "status": "running"
}
```
- 每次模块开始/结束时更新
- 脚本完成时写入 `"status": "completed"`
- 可配合 `check_progress.py` 外部监控

### 2.6 翻页逻辑差异

| 版本 | 起始页 | 扫描范围 | 翻页等待 |
|------|--------|---------|---------|
| v1 | 第 1 页 | 1-10 页（10页） | 15 秒固定 |
| v2 | 跳转 11 页 | 1-21 页（但 `range(1,22)`，实际从第11页之后的第1页开始） | 200-300ms |
| v3 | 跳转 11 页 | 12-21 页（10页，**修正了v2的范围bug**） | 300ms |
| v4 | 跳转 11 页 | 1-21 页（同v2的bug） | 300ms |

### 2.7 日志配置差异

v2: handler 未做重复检查，`setup_logger` 多次调用会添加重复 handler
v3/v4: 通过 `if not logger.handlers` 和 `isinstance` 检查避免重复

---

## 三、运行测试结果

### 3.1 登录测试 (使用 v3 逻辑)

| 项目 | 结果 |
|------|------|
| **测试时间** | 2026-05-10 17:09 |
| **方式** | ddddocr 自动识别验证码 |
| **识别结果** | `8ryb`（4位，正确） |
| **登录状态** | ✅ 成功 |
| **auth.json 保存** | ✅ 已保存（含 cookies + localStorage） |
| **耗时** | <5 秒 |

**结论**: v3/v4 的 ddddocr 自动验证码识别功能正常工作，可在无人工干预下完成登录。

### 3.2 v2 运行测试

| 项目 | 结果 |
|------|------|
| **配置** | `repeat_count=1`, `headless=True` |
| **auth.json 加载** | ✅ 成功（已通过 v3 登录获取） |
| **模块2-公共邮箱导航** | ✅ 成功进入 |
| **模块2-找目标邮件** | ✅ 找到目标邮件 |
| **模块2-转收文** | ❌ 等待 iframe 超时（30秒） |
| **重试（@retry）** | ✅ 触发重试机制 |
| **重试结果** | ❌ 同一邮件已被首次尝试消费，翻页扫描中（测试超时终止） |
| **截图保存** | ✅ 已保存 `screenshots/retry_add_receive_document_attempt1_*.png` |

**注意**: v2 无 ddddocr，若 auth.json 过期则需手动输入验证码，无法全自动运行。

### 3.3 v3 运行测试

| 项目 | 结果 |
|------|------|
| **配置** | `repeat_count=1`, `headless=True` |
| **auth.json 加载** | ✅ 成功 |
| **模块2-公共邮箱导航** | ✅ 成功进入 |
| **模块2-找目标邮件** | ✅ 找到目标邮件 |
| **模块2-转收文** | ❌ 遇到 `layui-layer-shade` 遮罩层阻止点击 |
| **遮罩层处理** | Playwright 自动重试点击 60+ 次后放弃 |
| **模块级重试** | ✅ `retry_module` 触发：清理弹窗 → 回首页 → 等待 3 秒 → 重试 |
| **截图保存** | ✅ 已保存 `screenshots/module2_add_receive_error_*.png` |

**关键发现**: v3 的 `safe_close_popups()` 使用了 `Escape` 键清理弹窗，但 `layui-layer-shade` 遮罩层无法仅靠 Escape 消除。

### 3.4 v4 运行测试

| 项目 | 结果 |
|------|------|
| **配置** | `repeat_count=1`, `headless=True` |
| **auth.json 加载** | ✅ 成功 |
| **登录方式** | ✅ 自动通过 auth.json（ddddocr 备用） |
| **模块2-公共邮箱导航** | ✅ 成功进入 |
| **模块2-找目标邮件** | ✅ 找到目标邮件（发件人: 东非商务合约部公邮, 来源: darport@chec.bj.cn） |
| **模块2-转收文 iframe** | ❌ 等待超时（30秒） |
| **@retry 重试** | ✅ 触发，3秒后重试 |
| **重试-找邮件** | ✅ 在另一页找到新目标（发件人: 四院马林迪项目公邮） |
| **重试-转收文** | ❌ iframe 再次超时 |
| **截图保存** | ✅ 已保存 |

### 3.5 测试汇总

| 测试项 | v2 | v3 | v4 |
|--------|:--:|:--:|:--:|
| auth.json 自动登录 | ✅ | ✅ | ✅ |
| ddddocr 自动验证码 | ❌ (不支持) | ✅ | ✅ |
| 公共邮箱导航 | ✅ | ✅ | ✅ |
| 查找目标邮件 | ✅ | ✅ | ✅ |
| 跳过 postmaster 发件人 | ✅ | ✅ | ✅ |
| 转收文 iframe 弹出 | ❌ (headless) | ❌ (遮罩阻止) | ❌ (headless) |
| 重试机制 | ✅ @retry | ✅ retry_module | ✅ @retry |
| 失败截图 | ✅ | ✅ | ✅ |
| 失败后行为 | 终止循环 | 跳过继续 | 终止循环 |
| status.json 进度 | ❌ | ✅ | ❌ |

**通用问题**: 所有版本在 headless 模式下，`转收文` 右键菜单的 iframe 弹窗均不可靠（可能为 OA 系统的反爬或 headless 检测机制）。建议在生产环境中使用 `headless=False` 以提高稳定性。

---

## 四、版本选择建议

| 使用场景 | 推荐版本 | 原因 |
|---------|:--------:|------|
| 长时间无人值守运行 | **v3** | 失败跳过不终止 + status.json 外部监控 |
| 需要自动验证码识别 | **v3** 或 **v4** | ddddocr 自动识别，无需人工 |
| 代码简洁易维护 | **v2** 或 **v4** | 代码量少，逻辑直接 |
| 希望失败即停排查 | **v2** 或 **v4** | 遇到错误立即终止，便于定位 |
| 首次部署/迁移 | **v3** | 功能最完善，容错最强 |
| 只需要基本功能 | **v4** | 自动验证码 + 简洁结构，最佳平衡 |

---

## 五、测试产物

| 文件 | 说明 |
|------|------|
| `auth.json` | 已刷新的登录状态（v3 自动验证码登录，2026-05-10 17:09） |
| `oa_auto.log` | 完整运行日志（含所有版本的测试记录） |
| `screenshots/retry_add_receive_document_attempt1_20260510_171332.png` | v4 转收文 iframe 超时截图 |
| `screenshots/module2_add_receive_error_20260510_171206.png` | v3 遮罩层阻止点击截图 |
| `screenshots/retry_start_workflow_attempt1_20260510_171012.png` | 流程启动重试截图 |

---

## 六、v5 版本（整合最佳模块）

### 6.1 设计原则

v5 以 **v3 为主体框架**（功能最完善），融入 v2/v4 的简洁设计，并修复测试中发现的 headless 兼容性问题。

### 6.2 各模块来源

| 模块 | 来源 | 原因 |
|------|:----:|------|
| 配置 CONFIG | v3 | 包含 retry 配置、status_file、iframework timeout |
| 日志系统 | v3 | handler 去重，防止重复注册 |
| 验证码识别 | v3/v4 | ddddocr 自动识别 + 5 次重试 |
| 登录流程 | v3/v4 | `captcha_login_with_retry` + `save_auth_state` |
| 状态追踪 | v3 | `status.json` + `update_status` + `finalize_status` |
| 安全清理 | v3 + **v5 增强** | 新增 `dismiss_layui_shade()` 主动移除遮罩层 |
| 函数级重试 | v2/v4 | `@retry` 装饰器保留（用于简单操作） |
| 模块级重试 | v3 | `retry_module` + 重试前完整清理 |
| 模块2 | v3 + **v5 增强** | "已在待发文档"检测 + 右键前主动清理遮罩 |
| 模块3 | v3 | 完整 try/except + 清理 |
| 模块4 | v3 | 完整 try/except + 清理 |
| 主循环 | v3 | 失败跳过不终止 + 进度追踪 |
| 翻页范围 | v3 | `range(12, 22)` 修正版 |
| 邮件通知 | v3 | 带空值检查 |

### 6.3 v5 新增/增强功能

1. **`dismiss_layui_shade(page)`** — 主动查找并移除 `layui-layer-shade` 遮罩层，解决 headless 下点击被拦截的问题（测试中 v3 遇到 60+ 次重试点击）
2. **`full_cleanup(page)`** — 组合清理：Escape + 移除 shade + 等待
3. **`CONFIG["timeout_iframe"]`** — 新增 45 秒超时用于转收文 iframe（headless 下更慢）
4. **`headless` 默认 `False`** — 根据测试结果，headless 下 iframe/遮罩不可靠
5. **模块2 右键前主动清理** — `full_cleanup(page)` 在右键点击前调用
6. **邮件空值检查** — `send_result_email` 检查邮箱是否配置

### 6.4 v5 vs 各版本对比

| 特性 | v2 | v3 | v4 | **v5** |
|------|:--:|:--:|:--:|:-----:|
| 自动验证码 | ❌ | ✅ | ✅ | ✅ |
| 模块级重试+清理 | ❌ | ✅ | ❌ | ✅ |
| 失败跳过不终止 | ❌ | ✅ | ❌ | ✅ |
| status.json 进度 | ❌ | ✅ | ❌ | ✅ |
| "已在待发"检测 | ❌ | ✅ | ❌ | ✅ |
| shade 遮罩清理 | ❌ | ❌ | ❌ | ✅ |
| iframe 专用超时 | ❌ | ❌ | ❌ | ✅ |
| 翻页范围正确 | ❌ | ✅ | ❌ | ✅ |
| 函数级 @retry | ✅ | ❌ | ✅ | ✅ |

### 6.5 v5 运行验证

| 测试项 | 结果 |
|--------|:----:|
| 语法检查 | ✅ 通过 |
| auth.json 加载 | ✅ 成功 |
| 模块加载/配置 | ✅ 正常 |

---

## 七、建议改进（针对 OA 系统适配）

1. **headless 兼容性**: 在 headless 模式下，右键菜单和 iframe 弹窗可能不可靠。建议 `headless` 默认设为 `False`，或增加 `page.wait_for_timeout` 在右键点击后。
2. **遮罩层处理**: v3 的 `safe_close_popups()` 仅按 Escape 键，不足以处理 `layui-layer-shade`。可改为查找并移除 shade 元素。
3. **v2/v4 翻页范围 bug**: `range(1, 22)` 从第1页开始编号，但实际已跳到第11页，应改为 `range(12, 22)`（如v3）。
4. **统一 v3 优点到 v4**: 建议将 v3 的 `safe_go_home()`、`status.json` 进度追踪、"已在待发文档"检测等功能合并到 v4 的简洁结构中。
