# CHEC-OA — OA 自动化脚本

基于 Playwright 的 OA 系统自动化脚本，支持自动登录（验证码识别）、邮件收文、流程启动、流程审批。

## 项目结构

```
├── oa_auto_v1.py              # v1 原始版
├── oa_auto_v2.py              # v2 集中配置 + 重试
├── oa_auto_v3.py              # v3 自动验证码 + 失败跳过
├── oa_auto_v4.py              # v4 自动验证码 + 简洁结构
├── oa_auto_v5.py              # v5 最佳模块整合
├── oa_auto_v6.py              # v6 配置外部化（推荐使用）
├── config.example.json        # v6 配置模板（复制为 config.json 后填入真实信息）
├── REPORT.md                  # 多版本对比与测试报告
├── oa_auth_v1/                # v1 辅助：独立登录保存工具
├── 分步函数/                   # 分步骤独立脚本
└── 附属代码/                   # 辅助工具（发件人提取、auth 测试等）
```

## 快速开始（v6 推荐）

### 1. 环境准备

```bash
# Python 3.8+
pip install playwright ddddocr
playwright install chromium
```

### 2. 配置

```bash
cp config.example.json config.json
# 编辑 config.json，填入你的 OA 账号、邮箱等真实信息
```

`config.json` 中需要修改的核心字段：

| 字段 | 说明 |
|------|------|
| `login.login_url` | OA 登录页 URL |
| `login.home_url` | OA 首页 URL |
| `login.username` / `login.password` | 登录账号密码 |
| `email.*` | 邮件通知 SMTP 配置 |
| `business.target_sources` | 目标来源邮箱列表 |
| `business.operator` | 审批操作人 |
| `sender_code_map` | 发件人→编号映射表（数组格式，增删条目直接加减行） |
| `source_code_map` | 来源邮箱→编号映射表 |
| `source_project_map` | 来源邮箱→项目名称映射表 |

### 3. 运行

```bash
python oa_auto_v6.py
```

首次运行会自动弹出浏览器进行验证码识别（需安装 ddddocr），登录成功后将保存 `auth.json`，后续运行自动复用。

### 4. 停止

按 `Ctrl+C` 终止。

## 版本演进

| 版本 | 核心特性 | 适用场景 |
|------|---------|---------|
| **v1** | 手动验证码，基础功能 | 参考原型 |
| **v2** | CONFIG 集中配置、logging 日志、@retry 装饰器、失败截图 | 需要日志和重试 |
| **v3** | ddddocr 自动验证码、模块级重试、失败跳过不终止、status.json 进度 | 长时无人值守 |
| **v4** | v3 验证码 + v2 简洁结构 | 简洁 + 自动登录 |
| **v5** | 各版本最佳模块整合 + shade 遮罩修复 | 稳定生产 |
| **v6** | **配置外部化**，主代码零敏感信息，映射表格化 | **推荐使用** |

详细对比见 [REPORT.md](REPORT.md)。

## 配置外部化（v6）

v6 将以下内容从代码中分离到 `config.json`：

- 登录 URL / 账号 / 密码
- SMTP 邮件配置
- 业务参数（收文类型、流程名称、操作人等）
- 发件人编号映射表
- 来源邮箱映射表
- 项目名称映射表

**映射表采用数组格式**，增删条目只需在 `config.json` 中加减一行，无需修改 Python 代码：

```json
"sender_code_map": [
  {"sender": "发件人名称A", "code": "CODEA"},
  {"sender": "发件人名称B", "code": "CODEB"}
]
```

## 运行产物

| 文件 | 说明 |
|------|------|
| `auth.json` | 登录状态（约 20 小时有效），自动生成 |
| `seq_counter.json` | 文号序号计数器，自动维护 |
| `status.json` | 运行进度（v3/v5/v6），供外部监控 |
| `oa_auto.log` | 运行日志 |
| `screenshots/` | 失败截图目录 |

## 许可

MIT
