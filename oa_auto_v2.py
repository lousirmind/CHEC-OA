"""
OA 自动化脚本 v2.0
优化点：
  - 统一配置管理
  - 结构化日志（同时输出到控制台和文件）
  - 关键操作带重试装饰器
  - 减少固定 sleep，改用事件驱动等待
  - 失败时自动截图
  - Session 失效自动重新登录
  - 模块2~4 可独立开关
"""

import re
import json
import os
import smtplib
import logging
import functools
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from collections import defaultdict
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# =====================================================================
# ========================  集中配置  =================================
# =====================================================================
CONFIG = {
    # ---------- 登录 ----------
    "login_url":       "http://checea.edmcs.cn/cloudoa/login",
    "home_url":        "http://checea.edmcs.cn/cloudoa/",
    "username":        "ydtchen",
    "password":        "Lz156970.",
    "auth_file":       "auth.json",

    # ---------- 超时（毫秒） ----------
    "timeout_default": 30_000,
    "timeout_short":   10_000,
    "timeout_page":     8_000,   # 页面等待缓冲（替换大量固定 sleep）

    # ---------- 循环控制 ----------
    "repeat_count":    1000,
    "run_module2":     True,    # 添加收文
    "run_module3":     True,    # 启动流程
    "run_module4":     True,    # 流程审批

    # ---------- 浏览器 ----------
    "headless":        True,    # True=后台运行，False=显示窗口

    # ---------- 邮件通知 ----------
    "smtp_host":       "smtp.qq.com",
    "smtp_port":       465,
    "sender_email":    "1774316986@qq.com",
    "smtp_password":   "fummtmoxbexbfbfg",
    "recipient_email": "lz156970@gmail.com",

    # ---------- 文件路径 ----------
    "counter_file":    "seq_counter.json",
    "log_file":        "oa_auto.log",
    "screenshot_dir":  "screenshots",

    # ---------- 业务参数 ----------
    "receive_type":    "信函",
    "send_unit":       "当地其他公司",
    "send_method":     "E-MAIL",
    "process_name":    "收文流程",
    "operator":        "陈乙东庭（Chen Yidongting）",
    "target_sources":  ["darport@chec.bj.cn", "tzdmgp@chec.bj.cn"],
    "skip_senders":    ["postmaster@qiye.163.com"],
}

# ---------- 发信人编号映射 ----------
SENDER_CODE_MAP = {
    "东非商务合约部公邮":        "DFSWB",
    "ea. tech@check.bj.cn":     "DFKJB",
    "东非工程部公邮":             "DFGCB",
    "notice@qiye.163.com":      "WYY",
    "twaha.msita@ports.go.tz":  "TPA",
    "abdi. issa@ports.go.tz":   "TPA",
    "aggrey.nhnyete@ports.go.tz":"TPA",
    "des@ports.go.tz":          "DES",
    "dg@ports.go.tz":           "DP",
    "DPWDSM.SecurityAdm@dpworld.com": "DPW",
    "edmund@interconsult-tz.com": "PM",
    "Emmanuel Magori":           "PM",
    "四院马林迪项目公邮":          "SHY",
    "坦桑尼亚达港马林迪泊位改扩建项目公邮": "SHY",
}

SOURCE_CODE_MAP = {
    "darport@chec.bj.cn":  "MLD",
    "tzdmgp@chec.bj.cn":   "DMGP5-7",
}

SOURCE_PROJECT_MAP = {
    "darport@chec.bj.cn":  "坦桑尼亚达港马林迪泊位改扩建工程项目",
    "tzdmgp@chec.bj.cn":   "坦桑尼亚达港1-7号泊位堆场修复工程项目",
}

# =====================================================================
# ========================  日志配置  =================================
# =====================================================================
def setup_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger("oa_auto")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # 控制台
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件（UTF-8，追加模式）
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger

log = setup_logger(CONFIG["log_file"])

# =====================================================================
# ========================  工具函数  =================================
# =====================================================================
def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)

def screenshot(page, tag: str):
    """失败时自动截图，文件名含时间戳"""
    ensure_dir(CONFIG["screenshot_dir"])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{CONFIG['screenshot_dir']}/{tag}_{ts}.png"
    try:
        page.screenshot(path=path)
        log.info(f"📸 截图已保存: {path}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

def retry(max_times=3, delay_ms=2000, exceptions=(Exception,)):
    """装饰器：失败自动重试"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    log.warning(f"⚠️ {func.__name__} 第{attempt}/{max_times}次失败: {e}")
                    if attempt < max_times:
                        # 取 page 参数截图（约定第一个非 self 参数叫 page）
                        page = args[0] if args else None
                        if hasattr(page, 'screenshot'):
                            screenshot(page, f"retry_{func.__name__}_attempt{attempt}")
                        import time; time.sleep(delay_ms / 1000)
            raise last_err
        return wrapper
    return decorator

def wait(page, ms: int):
    """统一 wait，避免直接调用 wait_for_timeout 散落各处"""
    page.wait_for_timeout(ms)

# =====================================================================
# ========================  计数器  ===================================
# =====================================================================
def load_counter() -> dict:
    if os.path.exists(CONFIG["counter_file"]):
        with open(CONFIG["counter_file"], "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_counter(counter: dict):
    with open(CONFIG["counter_file"], "w", encoding="utf-8") as f:
        json.dump(counter, f, indent=2, ensure_ascii=False)

def get_sender_code(sender_name: str) -> str:
    name = sender_name.strip()
    if name in SENDER_CODE_MAP:
        return SENDER_CODE_MAP[name]
    for key, code in SENDER_CODE_MAP.items():
        if key.lower() == name.lower():
            return code
    return "UKN"

def generate_doc_code(source: str, sender: str, counter: dict) -> str:
    """生成形如 MLD-DFSWB-CHEC-0001 的唯一编号，并更新计数器"""
    src_code    = SOURCE_CODE_MAP.get(source, "UNKNOWN")
    sender_code = get_sender_code(sender)
    key         = f"{src_code}-{sender_code}-CHEC"
    seq         = counter.get(key, 0) + 1
    counter[key] = seq
    save_counter(counter)
    return f"{src_code}-{sender_code}-CHEC-{seq:04d}"

# =====================================================================
# ========================  登录模块  =================================
# =====================================================================
def is_logged_in(page) -> bool:
    try:
        page.get_by_title("邮件管理").wait_for(state="visible",
                                                timeout=CONFIG["timeout_short"])
        return True
    except PWTimeoutError:
        return False

def do_login(page) -> bool:
    """手动验证码登录，仅在 auth.json 失效时触发"""
    log.info("🔐 开始手动登录...")
    page.goto(CONFIG["login_url"])
    page.get_by_placeholder("请输入用户名").fill(CONFIG["username"])
    page.get_by_placeholder("请输入密码").fill(CONFIG["password"])

    captcha = page.get_by_role("textbox", name="验证码")
    captcha.scroll_into_view_if_needed()
    captcha.click()

    input("👀 请在浏览器中输入验证码，然后按回车键继续 --> ")
    page.get_by_role("button", name="登 录").click()

    try:
        page.get_by_title("邮件管理").wait_for(state="visible", timeout=15_000)
        log.info("✅ 手动登录成功")
        # 保存新的 session
        page.context.storage_state(path=CONFIG["auth_file"])
        log.info(f"💾 新的登录状态已保存至 {CONFIG['auth_file']}")
        return True
    except PWTimeoutError:
        log.error("❌ 登录失败：超时未检测到首页元素")
        screenshot(page, "login_failed")
        return False

# =====================================================================
# ========================  模块2：添加收文  ==========================
# =====================================================================
def get_cell_text_by_header(row, frame, header_text: str) -> str:
    headers = [h.strip() for h in frame.locator("thead tr th").all_text_contents()]
    col_index = -1
    if header_text in headers:
        col_index = headers.index(header_text)
    else:
        for idx, h in enumerate(headers):
            if header_text in h:
                col_index = idx
                break
    if col_index == -1:
        return ""
    cells = row.locator("td").all()
    return cells[col_index].inner_text().strip() if col_index < len(cells) else ""

def click_next_page(frame, page) -> bool:
    for sel in [">", "下一页"]:
        btn = frame.locator("div.layui-table-page").get_by_text(sel, exact=True)
        if btn.count():
            break
    else:
        btn = frame.locator("a.layui-laypage-next")

    if not btn.count():
        log.warning("❌ 未找到下一页按钮")
        return False

    cls = btn.get_attribute("class") or ""
    if "disabled" in cls:
        log.info("已到最后一页")
        return False

    btn.click()
    try:
        frame.locator("tbody tr").first.wait_for(state="attached",timeout=3000)  #CONFIG["timeout_default"])
    except PWTimeoutError:
        frame.locator("tbody").wait_for(state="visible", timeout=3000)  #CONFIG["timeout_default"])
    page.wait_for_timeout(200)  # 👈 200 毫秒 = 0.2 秒，你可以改成 100、300 等
#    wait(page, CONFIG["timeout_page"])
    return True

def find_target_mail(page):
    """扫描所有分页，找到第一封符合条件的"未转收文"邮件，返回 (row, source, sender) 或 None"""
    mail_frame = page.frame_locator("iframe").first
    mail_frame.locator("tbody tr").first.wait_for(state="attached",
                                                   timeout=CONFIG["timeout_default"])
    # 设置每页90条
    mail_frame.get_by_role("combobox").select_option("90")
    mail_frame.locator("tbody tr").first.wait_for(state="attached",
                                                   timeout=CONFIG["timeout_default"])
    wait(page, CONFIG["timeout_page"])

    target_sources = CONFIG["target_sources"]
    skip_senders   = CONFIG["skip_senders"]

    # ---------- 新增：先翻到第 11 页 ----------
    log.info("⏩ 快速翻页到第 11 页...")
# 手动设置翻页等待时间（单位：毫秒），可根据网络状况调整
    FAST_PAGE_WAIT_MS = 300  # 👈 300 毫秒，你觉得慢可以改成 100，觉得不稳可改成 500

    for _ in range(1):
       if not click_next_page(mail_frame, page):
          log.warning("⚠️ 页数不足，无法到达第 11 页")
          return None
       mail_frame = page.frame_locator("iframe").first
       page.wait_for_timeout(FAST_PAGE_WAIT_MS)   # 使用手动可调的短等待
       log.info("✅ 已到达第 11 页，开始扫描...")
    # ----------------------------------------

    for page_num in range(1, 22):   # 从第 11 页开始扫描
        log.info(f"🔍 检查第 {page_num} 页...")
        # 每次翻页后重新拿 frame（防止 frame 失效）
        mail_frame = page.frame_locator("iframe").first
        rows = mail_frame.locator("tbody tr").all()

        for row in rows:
            if row.locator("td").filter(has_text=re.compile(r"未转收文")).count() == 0:
                continue
            sender = get_cell_text_by_header(row, mail_frame, "发件人")
            source = get_cell_text_by_header(row, mail_frame, "来源")

            if any(s in sender for s in skip_senders):
                log.info(f"⏭️ 跳过: {sender}")
                continue
            if any(t in source for t in target_sources):
                log.info(f"✅ 第 {page_num} 页找到目标邮件 | 发件人: {sender} | 来源: {source}")
                return row, source, sender

        log.info(f"⚠️ 第 {page_num} 页无目标邮件，尝试翻页...")
        if not click_next_page(mail_frame, page):
            break

    return None

@retry(max_times=2, delay_ms=3000)
def add_receive_document(page) -> bool:
    log.info("📧 模块2：添加收文...")
    counter = load_counter()

    # 1. 打开公共邮箱
    mail_manage  = page.get_by_title("邮件管理")
    public_mail  = page.get_by_text("公共邮箱")
    if not public_mail.is_visible():
        mail_manage.click()
        wait(page, 1000)
    public_mail.click()
    wait(page, CONFIG["timeout_page"])

    # 2. 找目标邮件
    result = find_target_mail(page)
    if result is None:
        log.warning("❌ 所有页均无符合条件的未转收文邮件")
        return False
    target_row, matched_source, matched_sender = result

    # 3. 右键 → 转收文
    page.keyboard.press("Escape")
    wait(page, 200)
    subject_link = target_row.locator("a").first
    subject_link.click(button="right")

    mail_frame = page.frame_locator("iframe").first
    try:
        mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible",
                                                               timeout=CONFIG["timeout_short"])
    except PWTimeoutError:
        subject_link.click(button="right")
        mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible",
                                                               timeout=CONFIG["timeout_short"])
    mail_frame.get_by_text("转收文", exact=True).click()

    # 4. 等待弹窗 iframe
    log.info("⏳ 等待转收文表单...")
    page.wait_for_selector('iframe[name*="layui-layer-iframe"]',
                           state="attached", timeout=CONFIG["timeout_default"])
    iframe_els = page.locator('iframe[name*="layui-layer-iframe"]').all()
    if not iframe_els:
        raise Exception("未找到转收文弹窗 iframe")
    last_name  = iframe_els[-1].get_attribute("name")
    trans_frame = page.frame_locator(f"iframe[name='{last_name}']").first

    try:
        trans_frame.get_by_placeholder("请选择").first.wait_for(state="visible",
                                                                 timeout=CONFIG["timeout_default"])
    except PWTimeoutError:
        wait(page, CONFIG["timeout_page"])
        trans_frame = page.frame_locator(f"iframe[name='{last_name}']").first
        trans_frame.get_by_placeholder("请选择").first.wait_for(state="visible",
                                                                 timeout=CONFIG["timeout_short"])
    wait(page, CONFIG["timeout_page"])

    # 5. 生成动态编号
    doc_code = generate_doc_code(matched_source, matched_sender, counter)
    selected_project = SOURCE_PROJECT_MAP.get(
        matched_source, "坦桑尼亚达港马林迪泊位改扩建工程项目")
    log.info(f"📝 发信方编码: {doc_code}  |  项目: {selected_project}")

    # 6. 填写表单
    # 6.1 收文类型
    type_sel = trans_frame.locator("div").filter(
        has_text=re.compile(r"^请选择信函$")).get_by_placeholder("请选择")
    type_sel.click()
    trans_frame.locator("dd").filter(
        has_text=re.compile(r"^信函$")).wait_for(state="visible", timeout=CONFIG["timeout_short"])
    trans_frame.locator("dd").filter(has_text=re.compile(r"^信函$")).click()
    wait(page, 3000)

    # 6.2 发信方编码
    code_input = trans_frame.locator(
        "//label[contains(text(),'发信方编码')]/following-sibling::div//input")
    code_input.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    code_input.fill(doc_code)

    # 6.3 发文单位
    unit_sel = trans_frame.get_by_role("textbox", name="请选择", exact=True).nth(1)
    unit_sel.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    unit_sel.click()
    unit_opt = trans_frame.get_by_text(CONFIG["send_unit"]).nth(1)
    unit_opt.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    unit_opt.click()
    wait(page, 3000)

    # 6.4 发送方式
    method_sel = trans_frame.locator("div").filter(
        has_text=re.compile(r"^请选择E-MAIL纸质信函$")).get_by_placeholder("请选择")
    method_sel.click()
    method_opt = trans_frame.locator("dd").filter(has_text=CONFIG["send_method"])
    method_opt.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    method_opt.click()
    wait(page, 3000)

    # 6.5 项目名称
    proj_sel = trans_frame.get_by_placeholder("请选择项目名称")
    proj_sel.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    proj_sel.click()
    proj_opt = trans_frame.locator("dd").filter(has_text=selected_project)
    proj_opt.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    proj_opt.click()
    wait(page, 3000)

    # 6.6 文号
    trans_frame.locator("#destinationrad").fill(doc_code)

    # 6.7 点击图标
    trans_frame.locator("i.layui-icon:has-text('')").first.click()
    page.wait_for_timeout(5000)

    # 7. 保存
    trans_frame.get_by_role("button", name="保 存").click()
    try:
        page.wait_for_selector('iframe[name*="layui-layer-iframe"]',
                               state="detached", timeout=CONFIG["timeout_short"])
        log.info("✅ 转收文弹窗已关闭")
    except PWTimeoutError:
        log.warning("⚠️ 弹窗关闭超时，继续执行")

    wait(page, 2000)
    log.info("✅ 模块2：收文添加完成")
    return True

# =====================================================================
# ========================  模块3：启动流程  ==========================
# =====================================================================
@retry(max_times=2, delay_ms=3000)
def start_workflow(page) -> bool:
    log.info("🚀 模块3：启动收文流程...")

    # 1. 打开待发文档
    doc_manage  = page.get_by_title("文档管理")
    pending_doc = page.get_by_text("待发文档", exact=True)
    if not pending_doc.is_visible():
        doc_manage.click()
        wait(page, CONFIG["timeout_page"])
    pending_doc.click()

    page.wait_for_selector("iframe", state="attached", timeout=CONFIG["timeout_short"])
    doc_frame = page.frame_locator("iframe").first
    doc_frame.locator("tbody tr").first.wait_for(state="attached",
                                                  timeout=CONFIG["timeout_default"])

    # 2. 勾选第一行
    checkbox = doc_frame.locator(
        "td.layui-table-col-special.hide-grid div.layui-form-checkbox").first
    if checkbox.count() == 0:
        checkbox = doc_frame.locator("tbody tr").first.locator("div.layui-form-checkbox")
    if checkbox.count() == 0:
        checkbox = doc_frame.locator("i.layui-icon-o, i.layui-icon-ok").first
    checkbox.click()
    log.info("✅ 已勾选第一行")
    wait(page, CONFIG["timeout_page"])

    # 3. 点击"流程"
    doc_frame.get_by_role("button", name="流程").click()
    wait(page, CONFIG["timeout_page"])

    # 4. 选择流程模板
    try:
        process_sel = doc_frame.locator(
            "label:has-text('流程模板')").locator("..").get_by_placeholder("请选择")
        process_sel.click()
    except Exception:
        doc_frame.get_by_placeholder("请选择").first.click()
    doc_frame.locator("dd").filter(has_text=CONFIG["process_name"]).click()
    log.info(f"✅ 已选择流程模板: {CONFIG['process_name']}")

    # 5. 等待单选框
    wait(page, 2000)

    # 6. 选择 dcc
    dcc = doc_frame.get_by_text("dcc", exact=True)
    if dcc.count():
        dcc.click()
    else:
        doc_frame.locator("input[type='radio'][value='dcc']").click()
    log.info("✅ 已选 dcc 节点")
    wait(page, 2000)

    # 7. 点击操作人选择框
    doc_frame.get_by_placeholder("请选择dcc节点操作人").click()
    wait(page, 2000)

    # 8. 处理选人弹窗
    log.info("⏳ 等待选人弹窗...")
    page.wait_for_selector('iframe[name*="layui-layer"]',
                           state="attached", timeout=CONFIG["timeout_short"])
    user_frame = page.frame_locator('iframe[name*="layui-layer"]').last
    operator_el = user_frame.get_by_text(CONFIG["operator"], exact=True)
    operator_el.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    wait(page, CONFIG["timeout_page"])
    operator_el.click()
    log.info(f"✅ 已选择操作人: {CONFIG['operator']}")
    wait(page, 1000)

    # 9. 点击确定
    confirm_btn = page.locator("a.layui-layer-btn0:visible")
    confirm_btn.wait_for(state="visible", timeout=CONFIG["timeout_short"])
    confirm_btn.click()
    log.info("✅ 已点击确认")
    wait(page, CONFIG["timeout_page"])

    # 10. 启动流程
    start_btn = doc_frame.get_by_role("button", name="启动流程")
    if start_btn.count() == 0:
        start_btn = page.get_by_role("button", name="启动流程")
    start_btn.click()
    log.info("✅ 模块3：流程已启动")
    wait(page, 3000)
    return True

# =====================================================================
# ========================  模块4：流程审批  ==========================
# =====================================================================
# ================== 模块4：流程审批 ==================
def approve_workflow(page, opinion="同意"):
    """从首页待办进入该收文流程，提交审批"""
    print("✍️ 开始流程审批...")
    # 回到首页
    page.get_by_title("首页").click()
    # 首页待办列表在 iframe 中
    home_frame = page.frame_locator("iframe").first
    page.wait_for_timeout(10000)
    
    # 直接点击第一个包含“收文流程”的链接（优先在主页面查找，若失败则在iframe中查找）
    # 等待待办任务出现，最多等待15秒
    try:
        todo_link = page.locator("a:has-text('收文流程')").first
        todo_link.wait_for(state="visible", timeout=15000)
    except:
        try:
            todo_link = home_frame.locator("a:has-text('收文流程')").first
            todo_link.wait_for(state="visible", timeout=15000)
        except:
            print("❌ 未找到待办任务")
            return False
    
    link_text = todo_link.inner_text()
    print(f"找到待办任务: {link_text}")
    todo_link.click()
    print("✅ 已点击待办任务")
    
    # 等待弹窗加载（给足够时间）
    page.wait_for_timeout(3000)
    
    # 全局查找提交按钮（遍历所有 frame 和主页面）
    submit_btn = None
    # 先尝试在主页面查找
    try:
        btn = page.locator("#executeTask").first
        if btn.is_visible(timeout=2000):
            submit_btn = btn
            print("在主页面找到提交按钮")
    except:
        pass
    
    # 如果主页没有，遍历所有 iframe
    if not submit_btn:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                btn = frame.locator("#executeTask").first
                if btn.is_visible(timeout=2000):
                    submit_btn = btn
                    print(f"在 iframe '{frame.name}' 中找到提交按钮")
                    break
            except:
                continue
    
    if not submit_btn:
        # 调试：截图并打印所有 frame 信息
        page.screenshot(path="debug_no_submit_btn.png")
        print("所有 frames:")
        for f in page.frames:
            print(f"  name={f.name}, url={f.url}")
        raise Exception("未找到提交按钮 #executeTask")
    
    # 点击提交按钮
    try:
        submit_btn.click()
        print("已点击提交按钮")
    except Exception as e:
        print(f"点击提交按钮失败: {e}")
        raise
    
    # 处理二次确认弹窗（可能为新 iframe 或原生 dialog）
    page.wait_for_timeout(2000)
    try:
        # 查找确认按钮（常见为“确定”或“确 定”）
        confirm_btn = None
        # 先检查主页面
        for selector in ["button:has-text('确定')", "button:has-text('确 定')"]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    confirm_btn = btn
                    break
            except:
                pass
        if not confirm_btn:
            for frame in page.frames:
                for selector in ["button:has-text('确定')", "button:has-text('确 定')"]:
                    try:
                        btn = frame.locator(selector).first
                        if btn.is_visible(timeout=10000):
                            confirm_btn = btn
                            break
                    except:
                        pass
                if confirm_btn:
                    break
        if confirm_btn:
            confirm_btn.click()
            print("已点击确认按钮")
        else:
            # 尝试原生 confirm
            page.once("dialog", lambda dialog: dialog.accept())
            print("尝试处理原生确认框")
    except Exception as e:
        print(f"确认弹窗处理失败: {e}")
    
    # 等待审批完成
    page.wait_for_timeout(3000)
    print("✅ 审批完成")
    return True


# =====================================================================
# ========================  邮件通知  =================================
# =====================================================================
def send_result_email(results: list):
    total   = len(results)
    success = sum(results)
    subject = f"OA自动化执行报告 — 成功 {success}/{total}"
    lines   = [f"共执行 {total} 次循环，成功 {success} 次，失败 {total - success} 次。\n"]
    for idx, ok in enumerate(results, 1):
        lines.append(f"  第 {idx:3d} 次: {'✅ 成功' if ok else '❌ 失败'}")
    body = "\n".join(lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"]    = Header(CONFIG["sender_email"])
    msg["To"]      = Header(CONFIG["recipient_email"])
    msg["Subject"] = Header(subject, "utf-8")

    try:
        srv = smtplib.SMTP_SSL(CONFIG["smtp_host"], CONFIG["smtp_port"])
        srv.login(CONFIG["sender_email"], CONFIG["smtp_password"])
        srv.sendmail(CONFIG["sender_email"], [CONFIG["recipient_email"]], msg.as_string())
        srv.quit()
        log.info("📧 结果邮件发送成功")
    except Exception as e:
        log.error(f"❌ 邮件发送失败: {e}")

# =====================================================================
# ========================  主函数  ===================================
# =====================================================================
def run_one_cycle(page, cycle_num: int) -> bool:
    """执行一次完整的业务循环（模块2→3→4），返回是否成功"""
    log.info(f"\n{'='*55}\n第 {cycle_num} 次循环开始\n{'='*55}")

    # 每次循环回到首页并清理状态
    page.goto(CONFIG["home_url"])
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PWTimeoutError:
        pass
    page.keyboard.press("Escape")
    wait(page, 500)

    try:
        if CONFIG["run_module2"]:
            if not add_receive_document(page):
                log.warning(f"第 {cycle_num} 次：模块2（添加收文）失败")
                return False

        if CONFIG["run_module3"]:
            if not start_workflow(page):
                log.warning(f"第 {cycle_num} 次：模块3（启动流程）失败")
                return False

        if CONFIG["run_module4"]:
            if not approve_workflow(page):
                log.warning(f"第 {cycle_num} 次：模块4（流程审批）失败")
                return False

    except Exception as e:
        log.error(f"第 {cycle_num} 次循环异常: {e}\n{traceback.format_exc()}")
        screenshot(page, f"cycle_{cycle_num}_error")
        return False

    log.info(f"✅ 第 {cycle_num} 次循环全部完成")
    return True


def main():
    ensure_dir(CONFIG["screenshot_dir"])
    log.info("🤖 OA 自动化脚本 v2.0 启动")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"])

        # 尝试加载已有 Session
        if os.path.exists(CONFIG["auth_file"]):
            context = browser.new_context(storage_state=CONFIG["auth_file"])
        else:
            context = browser.new_context()

        page = context.new_page()
        page.set_default_timeout(CONFIG["timeout_default"])
        page.goto(CONFIG["home_url"])

        # 检查登录状态
        if not is_logged_in(page):
            log.warning("⚠️ Session 已失效或不存在，触发手动登录...")
            if CONFIG["headless"]:
                # 无头模式下无法手动输入验证码，重启为有窗口模式
                log.info("🔄 切换到有窗口模式以完成验证码登录...")
                page.close(); context.close(); browser.close()
                browser  = p.chromium.launch(headless=False)
                context  = browser.new_context()
                page     = context.new_page()
                page.set_default_timeout(CONFIG["timeout_default"])
            if not do_login(page):
                log.error("登录失败，脚本退出")
                browser.close()
                return
            # 登录成功后切回无头模式（若需要）
            if CONFIG["headless"]:
                log.info("🔄 登录完成，切回无头模式继续执行...")
                page.close(); context.close(); browser.close()
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(storage_state=CONFIG["auth_file"])
                page    = context.new_page()
                page.set_default_timeout(CONFIG["timeout_default"])
                page.goto(CONFIG["home_url"])
        else:
            log.info("✅ 已通过 auth.json 自动登录")

        # ==================== 主循环 ====================
        results = []
        for i in range(1, CONFIG["repeat_count"] + 1):
            ok = run_one_cycle(page, i)
            results.append(ok)
            if not ok:
                log.error("❌ 本次循环失败，终止后续循环")
                break

        log.info(f"\n🎉 全部循环执行完毕！成功 {sum(results)}/{len(results)} 次")

        context.close()
        browser.close()

    # 发送汇总邮件
    send_result_email(results)


if __name__ == "__main__":
    main()