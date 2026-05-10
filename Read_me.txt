====================================================================
OA 自动化脚本 v3.0 使用手册
适用于任意 OA 账号，按教程配置即可运行
最后更新: 2026年4月
====================================================================

1. 环境准备

 1.1 安装 Python
- 需要 Python 3.8 或更高版本
- 检查版本：python3 --version

 1.2 安装依赖
打开终端，进入脚本所在目录，执行：
```bash
cd /path/to/your/auto_oa
source venv/bin/activate   # 如果有虚拟环境
pip install playwright ddddocr
playwright install chromium
```
说明：
- playwright: 浏览器自动化核心库
- ddddocr: 验证码自动识别库（强烈推荐安装，可实现全自动登录）

2. 配置你的账号

打开 `oa_auto_v2.py`，找到文件开头的 CONFIG 字典，修改以下必填项：

 2.1 登录配置（必填）
```python
CONFIG = {
    "login_url":       "你的OA登录页面URL",    # 例如 "http://your-oa.com/login"
    "home_url":        "你的OA首页URL",        # 例如 "http://your-oa.com/"
    "username":        "你的用户名",
    "password":        "你的密码",
    "auth_file":       "auth.json",            # 登录状态文件，无需修改
    ...
}
```

 2.2 浏览器配置（可选）
```python
    "headless":        True,    # True=后台静默运行，False=显示浏览器窗口
```
建议：首次使用时设为 `False` 观察运行过程，确认无误后再改为 `True`。

 2.3 循环次数（可选）
```python
    "repeat_count":    100,     # 设置要循环执行的次数
```

 2.4 模块开关（可选）
```python
    "run_module2":     True,    # 是否运行模块2（添加收文）
    "run_module3":     True,    # 是否运行模块3（启动流程）
    "run_module4":     True,    # 是否运行模块4（流程审批）
```
如需跳过某个模块，设为 `False` 即可。

 2.5 重试配置（可选）
```python
    "max_retries":     2,       # 每个模块失败时的最大重试次数
    "retry_delay":     3,       # 重试间隔（秒）
```

 2.6 超时配置（可选，网络不稳定时调整）
```python
    "timeout_default": 30_000,  # 默认超时（毫秒）
    "timeout_short":   10_000,  # 短超时
```

 2.7 邮件通知（可选，用于接收执行报告）
```python
    "smtp_host":       "smtp.qq.com",       # SMTP 服务器地址
    "smtp_port":       465,                  # 端口
    "sender_email":    "你的邮箱@qq.com",    # 发件人邮箱
    "smtp_password":   "你的SMTP授权码",     # SMTP 授权码（非登录密码）
    "recipient_email": "收件人邮箱@xx.com",  # 接收报告的邮箱
```
QQ邮箱获取SMTP授权码：登录QQ邮箱 → 设置 → 账户 → POP3/IMAP/SMTP服务 → 开启 → 生成授权码。
如果不需要邮件通知，可将三个邮箱地址留空或设为相同。

 2.8 业务参数（根据你的 OA 系统修改）
```python
    # ---------- 业务参数 ----------
    "receive_type":    "信函",              # 收文类型（下拉选项中的值）
    "send_unit":       "当地其他公司",       # 发文单位
    "send_method":     "E-MAIL",           # 发送方式
    "process_name":    "收文流程",          # 流程模板名称
    "operator":        "陈乙东庭",          # 审批操作人姓名
    "target_sources":  ["邮箱1@xx.com"],    # 目标来源邮箱列表（用于筛选邮件）
    "skip_senders":    ["postmaster@qiye.163.com"],  # 要跳过的发件人
```

 2.9 映射字典（根据实际业务修改）

这些字典用于将发件人名称映射为编号，生成文号：

```python
# 发件人名称 → 发件人编号
SENDER_CODE_MAP = {
    "发件人A": "ABC",
    "发件人B": "DEF",
}

# 来源邮箱 → 来源编号
SOURCE_CODE_MAP = {
    "source@company.com": "SRC",
}

# 来源邮箱 → 项目名称（填写表单时选择的项目）
SOURCE_PROJECT_MAP = {
    "source@company.com": "某某工程项目",
}
```
如果某个发件人不在映射表中，编号会使用 "UKN"（Unknown）。

3. 运行脚本

 3.1 首次运行
```bash
cd /path/to/auto_oa
source venv/bin/activate   # 激活虚拟环境
python oa_auto_v2.py
```
首次运行时：
- 如果已安装 ddddocr → 脚本自动识别验证码并完成登录
- 如果未安装 ddddocr → 脚本弹出浏览器窗口，请手动输入验证码后按回车
- 登录成功后自动保存 auth.json（有效期约 20 小时）

 3.2 后续运行
auth.json 有效期内，脚本自动登录，无需任何交互。

 3.3 停止运行
按 `Ctrl+C` 即可终止脚本。

4. 查看运行进度

脚本运行时，会自动将进度写入 `status.json` 文件。你可以用以下命令查看：

 4.1 查看一次
```bash
python check_progress.py
```
输出示例：
```
==================================================
🔄 OA 自动化脚本运行进度
==================================================
  状态:       running
  进度:       45/100 (45.0%)
  当前模块:   模块3-启动流程
  最新结果:   执行中...
  跳过次数:   2
  更新时间:   2026-04-13 15:30:00
==================================================
```

 4.2 持续监控（每 5 秒自动刷新）
```bash
python check_progress.py watch
```
按 `Ctrl+C` 退出监控模式。

 4.3 查看日志
日志文件 `oa_auto.log` 记录每一步的执行详情：
```bash
tail -f oa_auto.log      # 实时查看日志
tail -100 oa_auto.log    # 查看最后 100 行
```

 4.4 查看失败截图
失败时自动截图保存到 `screenshots/` 目录，文件名含时间戳。

5. 执行流程说明

每个循环执行以下步骤：
```
回到首页 → 模块2（添加收文）→ 模块3（启动流程）→ 模块4（流程审批）
```

 5.1 模块2：添加收文
1. 进入公共邮箱
2. 翻页查找目标来源邮箱的"未转收文"邮件
3. 右键 → 转收文
4. 填写表单（收文类型、发信方编码、发文单位、发送方式、项目名称、文号）
5. 保存
特殊处理：如果提示"已在待发文档中"，自动跳过转收文，直接进入模块3

 5.2 模块3：启动流程
1. 进入待发文档
2. 勾选第一行
3. 选择流程模板
4. 选择审批节点和操作人
5. 启动流程

 5.3 模块4：流程审批
1. 回到首页
2. 在待办列表中点击收文流程
3. 点击提交 → 确认

 5.4 失败处理机制
- 任何模块失败后，自动重试（次数可配置）
- 重试前自动清理弹窗、回到首页
- 重试用尽后跳过该模块，继续下一次循环（不终止整个脚本）
- 失败时自动截图
- 最终邮件报告汇总所有循环的成功/失败统计

6. 常见问题

 问题1：登录时一直要求输入验证码
- 确保 auth.json 文件存在且未过期（约 20 小时）
- 删除 auth.json 后重新运行脚本即可重新登录
- 建议安装 ddddocr 实现自动验证码识别：`pip install ddddocr`

 问题2：找不到目标邮件
- 检查公共邮箱中是否有来源邮箱匹配 `target_sources` 和 `SOURCE_CODE_MAP` 的邮件
- 检查邮件状态是否为"未转收文"
- 脚本默认从第 11 页开始扫描到第 21 页，可在代码中调整翻页范围

 问题3：表单填写时元素找不到（超时）
- 网络慢或 OA 响应延迟时，增大 `timeout_default` 值（单位毫秒）
- 首次运行建议设 `headless=False` 观察执行过程

 问题4：编号计数器不递增
- 脚本使用 `seq_counter.json` 持久化编号，请勿手动删除
- 如需重置编号，可删除该文件，脚本会重新从 1 开始

 问题5：邮件发送失败
- 检查 SMTP 授权码是否正确
- 检查发件人邮箱是否已开启 SMTP 服务
- 非 QQ 邮箱需修改 smtp_host 和 smtp_port

 问题6：如何修改每页显示条数
在 `add_receive_document` 函数中找到：
```python
mail_frame.get_by_role("combobox").select_option("90")
```
将 `"90"` 改为 OA 系统支持的其他值（如 `"50"`）。

 问题7：如何修改翻页起始页和范围
在 `find_target_mail` 函数中：
```python
for _ in range(11):          # 快速翻到第 11 页
for page_num in range(12, 22):  # 从第 12 页扫描到第 21 页
```

7. 项目文件说明

| 文件/目录 | 说明 |
|-----------|------|
| `oa_auto_v2.py` | 主脚本（v3.0），唯一需要运行的文件 |
| `check_progress.py` | 进度查看工具 |
| `save_auth.py` | 已废弃，保留仅作参考 |
| `auth.json` | 自动保存的登录状态（约 20 小时有效） |
| `seq_counter.json` | 文号序号计数器（勿手动删除） |
| `status.json` | 运行时进度状态文件（自动生成） |
| `oa_auto.log` | 运行日志文件（自动生成） |
| `screenshots/` | 失败时自动截图目录 |

8. 迁移到其他项目

如果你要将此脚本用于其他 OA 系统，需要修改的配置清单：

必填：
- [ ] `login_url` — 登录页 URL
- [ ] `home_url` — 首页 URL
- [ ] `username` — 用户名
- [ ] `password` — 密码

按需修改：
- [ ] `target_sources` — 目标来源邮箱
- [ ] `skip_senders` — 要跳过的发件人
- [ ] `SENDER_CODE_MAP` — 发件人编号映射
- [ ] `SOURCE_CODE_MAP` — 来源编号映射
- [ ] `SOURCE_PROJECT_MAP` — 项目名称映射
- [ ] `process_name` — 流程模板名称
- [ ] `operator` — 审批操作人
- [ ] 邮件相关配置

如果 OA 系统的页面结构（元素选择器）不同，还需要修改对应的定位代码。

====================================================================
