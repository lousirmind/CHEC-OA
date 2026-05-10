"""
OA 自动化脚本 v5.0
整合各版本最佳模块：
  - v3 的 ddddocr 自动验证码 + 重试登录
  - v3 的模块级重试（retry_module）+ 失败跳过不终止
  - v3 的 status.json 进度追踪 + safe 清理函数
  - v3 的"已在待发文档"检测
  - v2/v4 的 @retry 装饰器（用于函数级快速重试）
  - 修复：headless 下遮罩层处理增强
  - 修复：翻页范围修正为 range(12, 22)
  - 修复：转收文 iframe 超时增加 + 遮罩层等待
  - 新增：layui shade 遮罩层主动关闭
"""
import re, json, os, io, time, smtplib, logging, functools, traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

try:
    import ddddocr
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# =====================================================================
# ========================  集中配置  =================================
# =====================================================================
CONFIG = {
    # ---------- 登录 ----------
    "login_url":       "http://your-oa-server.com/cloudoa/login",
    "home_url":        "http://your-oa-server.com/cloudoa/",
    "username":        "your-username",
    "password":        "your-password",
    "auth_file":       "auth.json",

    # ---------- 超时（毫秒） ----------
    "timeout_default": 30_000,
    "timeout_short":   10_000,
    "timeout_page":     8_000,
    "timeout_iframe":  45_000,   # 转收文 iframe 等待（headless 下可能需要更长时间）

    # ---------- 循环控制 ----------
    "repeat_count":    1000,
    "run_module2":     True,
    "run_module3":     True,
    "run_module4":     True,

    # ---------- 重试配置（模块级） ----------
    "max_retries":     2,
    "retry_delay":     3,

    # ---------- 浏览器 ----------
    "headless":        False,    # 建议 False，headless 下遮罩/iframe 不可靠

    # ---------- 邮件通知 ----------
    "smtp_host":       "smtp.qq.com",
    "smtp_port":       465,
    "sender_email":    "your-email@qq.com",
    "smtp_password":   "your-smtp-auth-code",
    "recipient_email": "recipient@email.com",

    # ---------- 文件路径 ----------
    "counter_file":    "seq_counter.json",
    "log_file":        "oa_auto.log",
    "screenshot_dir":  "screenshots",
    "status_file":     "status.json",

    # ---------- 业务参数 ----------
    "receive_type":    "信函",
    "send_unit":       "当地其他公司",
    "send_method":     "E-MAIL",
    "process_name":    "收文流程",
    "operator":        "操作人姓名（Your Name）",
    "target_sources":  ["source1@company.com", "source2@company.com"],
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
    "source1@company.com":  "MLD",
    "source2@company.com":   "DMGP5-7",
}

SOURCE_PROJECT_MAP = {
    "source1@company.com":  "某某工程项目名称",
    "source2@company.com":   "另一个项目名称",
}

# =====================================================================
# ========================  日志配置  =================================
# =====================================================================
def setup_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger("oa_auto")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    if not logger.handlers:
        logger.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        logger.addHandler(fh)
    return logger

log = setup_logger(CONFIG["log_file"])

# =====================================================================
# ========================  工具函数  =================================
# =====================================================================
def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)

def wait(page, ms: int):
    page.wait_for_timeout(ms)

def screenshot(page, tag: str):
    ensure_dir(CONFIG["screenshot_dir"])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{CONFIG['screenshot_dir']}/{tag}_{ts}.png"
    try:
        page.screenshot(path=path)
        log.info(f"📸 截图已保存: {path}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

# =====================================================================
# ===============  v5 增强：遮罩层清理  ===============================
# =====================================================================
def safe_close_popups(page):
    """关闭可能残留的弹窗和遮罩层（v5 增强版）"""
    try:
        page.keyboard.press("Escape")
        wait(page, 300)
    except Exception:
        pass

def dismiss_layui_shade(page):
    """主动关闭 layui 遮罩层（v5 新增，解决 headless 下 shade 阻止点击的问题）"""
    try:
        shade = page.locator(".layui-layer-shade")
        if shade.count() > 0:
            shade.evaluate("el => el.remove()")
            log.debug("🧹 已移除 layui shade 遮罩层")
            wait(page, 200)
    except Exception:
        pass

def safe_go_home(page):
    """安全回到首页"""
    try:
        page.goto(CONFIG["home_url"], timeout=CONFIG["timeout_default"])
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PWTimeoutError:
            pass
        safe_close_popups(page)
        dismiss_layui_shade(page)
        wait(page, 500)
        return True
    except Exception as e:
        log.warning(f"回到首页失败: {e}")
        return False

def full_cleanup(page):
    """v5 新增：完整清理（Escape + 移除 shade + 等待）"""
    safe_close_popups(page)
    dismiss_layui_shade(page)
    wait(page, 500)

# =====================================================================
# ========================  状态追踪（v3 精华）=========================
# =====================================================================
def update_status(cycle_num: int, total: int, module: str, result: str, skipped: int = 0):
    status = {
        "current_cycle": cycle_num,
        "total_cycles":  total,
        "progress_pct":  round(cycle_num / total * 100, 1) if total > 0 else 0,
        "current_module": module,
        "last_result":   result,
        "skipped_count": skipped,
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status":        "running"
    }
    try:
        with open(CONFIG["status_file"], "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"写入状态文件失败: {e}")

def finalize_status(results: list):
    total = len(results)
    success = sum(results)
    status = {
        "current_cycle": total,
        "total_cycles":  total,
        "progress_pct":  100.0,
        "current_module": "完成",
        "last_result":   f"成功 {success}/{total}",
        "skipped_count": total - success,
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status":        "completed"
    }
    try:
        with open(CONFIG["status_file"], "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"写入状态文件失败: {e}")

# =====================================================================
# ========================  函数级重试装饰器（v2/v4）===================
# =====================================================================
def retry(max_times=3, delay_ms=2000, exceptions=(Exception,)):
    """装饰器：函数级快速重试（v2/v4 风格，用于简单操作）"""
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
                        page = args[0] if args else None
                        if hasattr(page, 'screenshot'):
                            screenshot(page, f"retry_{func.__name__}_attempt{attempt}")
                        time.sleep(delay_ms / 1000)
            raise last_err
        return wrapper
    return decorator

# =====================================================================
# ========================  验证码识别（v3/v4 精华）====================
# =====================================================================
def recognize_captcha(page, expected_len=4) -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        ocr = ddddocr.DdddOcr(show_ad=False)
        captcha_img = None
        for sel in [
            "img[src*='captcha']", "img[src*='code']", "img[src*='verify']",
            "img[alt*='验证码']", "img[title*='验证码']", "canvas",
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    captcha_img = el
                    break
            except Exception:
                continue
        if captcha_img is None:
            try:
                captcha_img = page.locator("form img, .login img").last
                if not captcha_img.is_visible(timeout=1000):
                    captcha_img = None
            except Exception:
                captcha_img = None
        if captcha_img is None:
            log.warning("⚠️ 未找到验证码图片元素")
            return ""
        img_bytes = captcha_img.screenshot()
        result = ocr.classification(img_bytes)
        result = result.strip().replace(" ", "").lower()
        if len(result) > expected_len:
            result = result[:expected_len]
        elif len(result) < expected_len:
            log.warning(f"⚠️ 识别结果仅 {len(result)} 位（期望 {expected_len} 位），将降级为手动输入")
            return ""
        log.info(f"🔤 验证码识别结果: {result} ({len(result)} 位)")
        return result
    except Exception as e:
        log.warning(f"验证码识别异常: {e}")
        return ""

def captcha_login_with_retry(page, max_attempts=5) -> bool:
    for attempt in range(1, max_attempts + 1):
        log.info(f"🔐 登录尝试 {attempt}/{max_attempts}")
        page.goto(CONFIG["login_url"], timeout=CONFIG["timeout_default"])
        page.get_by_placeholder("请输入用户名").fill(CONFIG["username"])
        page.get_by_placeholder("请输入密码").fill(CONFIG["password"])

        captcha_text = recognize_captcha(page, expected_len=4)
        if captcha_text and len(captcha_text) == 4:
            try:
                captcha_input = page.get_by_role("textbox", name="验证码")
                captcha_input.click()
                captcha_input.fill(captcha_text)
                log.info("✅ 验证码已自动填充")
            except Exception as e:
                log.warning(f"验证码填充失败: {e}")
                captcha_text = ""
        else:
            log.warning("⚠️ 验证码识别失败，请手动输入")
            captcha_input = page.get_by_role("textbox", name="验证码")
            captcha_input.scroll_into_view_if_needed()
            captcha_input.click()
            captcha_text = input("👀 请在浏览器中输入验证码（4位），然后按回车键继续 --> ")

        page.get_by_role("button", name="登 录").click()
        try:
            page.get_by_title("邮件管理").wait_for(state="visible", timeout=15_000)
            log.info("✅ 登录成功")
            save_auth_state(page)
            return True
        except PWTimeoutError:
            log.warning(f"❌ 第{attempt}次登录失败（验证码可能错误）")
            screenshot(page, f"login_failed_attempt{attempt}")
            if attempt < max_attempts:
                wait(page, 2000)

    log.error("❌ 登录重试次数用尽")
    screenshot(page, "login_failed")
    return False

def save_auth_state(page):
    try:
        page.context.storage_state(path=CONFIG["auth_file"])
        log.info(f"💾 登录状态已保存至 {CONFIG['auth_file']}")
    except Exception as e:
        log.warning(f"保存登录状态失败: {e}")

# =====================================================================
# ========================  登录检测  =================================
# =====================================================================
def is_logged_in(page) -> bool:
    try:
        page.get_by_title("邮件管理").wait_for(state="visible",
                                                timeout=CONFIG["timeout_short"])
        return True
    except PWTimeoutError:
        return False

# =====================================================================
# ========================  计数器（v3）===============================
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
    src_code    = SOURCE_CODE_MAP.get(source, "UNKNOWN")
    sender_code = get_sender_code(sender)
    key         = f"{src_code}-{sender_code}-CHEC"
    seq         = counter.get(key, 0) + 1
    counter[key] = seq
    save_counter(counter)
    return f"{src_code}-{sender_code}-CHEC-{seq:04d}"

# =====================================================================
# ========================  模块2：添加收文（v3 增强版）================
# =====================================================================
def get_cell_text_by_header(row, frame, header_text: str) -> str:
    try:
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
    except Exception as e:
        log.warning(f"获取单元格文本失败 ({header_text}): {e}")
        return ""

def click_next_page(frame, page) -> bool:
    try:
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
            frame.locator("tbody tr").first.wait_for(state="attached", timeout=5000)
        except PWTimeoutError:
            frame.locator("tbody").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(300)
        return True
    except Exception as e:
        log.warning(f"翻页失败: {e}")
        return False

def find_target_mail(page):
    """扫描分页，找到第一封符合条件的"未转收文"邮件（v3 修正版翻页范围）"""
    try:
        mail_frame = page.frame_locator("iframe").first
        mail_frame.locator("tbody tr").first.wait_for(state="attached",
                                                       timeout=CONFIG["timeout_default"])
        mail_frame.get_by_role("combobox").select_option("90")
        mail_frame.locator("tbody tr").first.wait_for(state="attached",
                                                       timeout=CONFIG["timeout_default"])
        wait(page, CONFIG["timeout_page"])
    except Exception as e:
        log.error(f"加载邮件列表失败: {e}")
        screenshot(page, "mail_list_load_failed")
        return None

    target_sources = CONFIG["target_sources"]
    skip_senders   = CONFIG["skip_senders"]

    # 快速翻到第 11 页（v3 修正：翻 11 次，每页 300ms）
    log.info("⏩ 快速翻页到第 11 页...")
    for _ in range(11):
        if not click_next_page(mail_frame, page):
            log.warning("⚠️ 页数不足，无法到达第 11 页")
            return None
        mail_frame = page.frame_locator("iframe").first
        page.wait_for_timeout(300)

    log.info("✅ 已到达第 11 页，开始扫描...")

    # v5 修正：从第 12 页扫描到第 21 页
    for page_num in range(12, 22):
        log.info(f"🔍 检查第 {page_num} 页...")
        try:
            mail_frame = page.frame_locator("iframe").first
            rows = mail_frame.locator("tbody tr").all()
        except Exception as e:
            log.warning(f"读取第 {page_num} 页邮件列表失败: {e}")
            break

        for row in rows:
            try:
                row_text = row.inner_text()
                if "未转收文" not in row_text:
                    continue
                sender = get_cell_text_by_header(row, mail_frame, "发件人")
                source = get_cell_text_by_header(row, mail_frame, "来源")
                log.debug(f"找到未转收文邮件 | 发件人: {sender} | 来源: {source}")
                if any(s in sender for s in skip_senders):
                    log.debug(f"⏭️ 跳过发件人: {sender}")
                    continue
                if source and any(t in source for t in target_sources):
                    log.info(f"✅ 第 {page_num} 页找到目标邮件 | 发件人: {sender} | 来源: {source}")
                    return row, source, sender
            except Exception as e:
                log.warning(f"处理邮件行时出错: {e}")
                continue

        if not click_next_page(mail_frame, page):
            break

    log.warning("❌ 所有页均无符合条件的未转收文邮件")
    return None

def add_receive_document(page) -> bool:
    """模块2：添加收文（v3 增强版 + v5 shade 处理）"""
    log.info("📧 模块2：添加收文...")
    try:
        counter = load_counter()

        # 1. 打开公共邮箱
        mail_manage  = page.get_by_title("邮件管理")
        public_mail  = page.get_by_title("公共邮箱")
        if not public_mail.is_visible():
            mail_manage.click()
            wait(page, 1000)
        public_mail.click()
        wait(page, CONFIG["timeout_page"])

        # 2. 找目标邮件
        result = find_target_mail(page)
        if result is None:
            log.warning("❌ 未找到符合条件的未转收文邮件，跳过本次收文添加")
            return False
        target_row, matched_source, matched_sender = result

        # 3. 右键 → 转收文（v5 增强：先清理遮罩层）
        full_cleanup(page)
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

        # 4. 等待弹窗 iframe（v5 增强：使用更长的 timeout_iframe）
        log.info("⏳ 等待转收文表单或提示...")
        try:
            page.wait_for_selector('iframe[name*="layui-layer-iframe"]',
                                   state="attached", timeout=CONFIG["timeout_iframe"])
        except PWTimeoutError:
            log.warning("⚠️ 未检测到转收文 iframe 弹窗")
            # 检查是否有"已在待发文档中"提示
            try:
                page_text = page.inner_text(timeout=5000)
                if "已在待发文档中" in page_text or "已在代发文档中" in page_text:
                    log.info("⚡ 检测到'已在待发文档中'提示，跳过转收文，直接进入模块3")
                    safe_close_popups(page)
                    wait(page, 1000)
                    return "skip_to_module3"
            except Exception:
                pass
            # 尝试重新右键
            log.warning("⚠️ 尝试重新右键菜单")
            full_cleanup(page)
            subject_link.click(button="right")
            mail_frame = page.frame_locator("iframe").first
            try:
                mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible",
                                                                       timeout=CONFIG["timeout_short"])
            except PWTimeoutError:
                raise Exception("右键菜单仍未出现")
            mail_frame.get_by_text("转收文", exact=True).click()
            page.wait_for_selector('iframe[name*="layui-layer-iframe"]',
                                   state="attached", timeout=CONFIG["timeout_iframe"])

        iframe_els = page.locator('iframe[name*="layui-layer-iframe"]').all()
        if not iframe_els:
            raise Exception("未找到转收文弹窗 iframe")
        last_name  = iframe_els[-1].get_attribute("name")
        resp_frame = page.frame_locator(f"iframe[name='{last_name}']").first

        # 检查是否为"已在待发文档中"提示（v3 精华）
        try:
            page_text = resp_frame.locator("body").inner_text(timeout=5000)
            if "已在待发文档中" in page_text or "已在代发文档中" in page_text:
                log.info("⚡ 该邮件已在待发文档中，跳过转收文，直接进入模块3")
                safe_close_popups(page)
                wait(page, 1000)
                return "skip_to_module3"
        except Exception:
            pass

        # v5 增强：等待表单时主动清理遮罩层
        dismiss_layui_shade(page)
        try:
            resp_frame.get_by_placeholder("请选择").first.wait_for(state="visible",
                                                                     timeout=CONFIG["timeout_default"])
        except PWTimeoutError:
            wait(page, CONFIG["timeout_page"])
            resp_frame = page.frame_locator(f"iframe[name='{last_name}']").first
            resp_frame.get_by_placeholder("请选择").first.wait_for(state="visible",
                                                                     timeout=CONFIG["timeout_short"])
        wait(page, CONFIG["timeout_page"])
        trans_frame = resp_frame

        # 5. 生成动态编号
        doc_code = generate_doc_code(matched_source, matched_sender, counter)
        selected_project = SOURCE_PROJECT_MAP.get(
            matched_source, "某某工程项目名称")
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

    except Exception as e:
        log.error(f"❌ 模块2（添加收文）执行异常: {e}")
        log.debug(traceback.format_exc())
        screenshot(page, "module2_add_receive_error")
        full_cleanup(page)
        return False

# =====================================================================
# ========================  模块3：启动流程（v3 增强版）================
# =====================================================================
def start_workflow(page) -> bool:
    """模块3：启动收文流程"""
    log.info("🚀 模块3：启动收文流程...")
    try:
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

    except Exception as e:
        log.error(f"❌ 模块3（启动流程）执行异常: {e}")
        log.debug(traceback.format_exc())
        screenshot(page, "module3_start_workflow_error")
        full_cleanup(page)
        return False

# =====================================================================
# ========================  模块4：流程审批（v3 增强版）================
# =====================================================================
def approve_workflow(page, opinion="同意") -> bool:
    """模块4：流程审批"""
    log.info("✍️ 模块4：流程审批...")
    try:
        page.get_by_title("首页").click()
        wait(page, 1000)
        home_frame = page.frame_locator("iframe").first
        page.wait_for_timeout(10000)

        todo_link = None
        try:
            todo_link = page.locator("a:has-text('收文流程')").first
            todo_link.wait_for(state="visible", timeout=15000)
        except PWTimeoutError:
            try:
                todo_link = home_frame.locator("a:has-text('收文流程')").first
                todo_link.wait_for(state="visible", timeout=15000)
            except PWTimeoutError:
                log.warning("❌ 未找到待办任务，跳过审批")
                return False

        link_text = todo_link.inner_text()
        log.info(f"找到待办任务: {link_text}")
        todo_link.click()
        wait(page, 3000)

        # 查找提交按钮
        submit_btn = None
        try:
            btn = page.locator("#executeTask").first
            if btn.is_visible(timeout=2000):
                submit_btn = btn
        except Exception:
            pass

        if not submit_btn:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    btn = frame.locator("#executeTask").first
                    if btn.is_visible(timeout=2000):
                        submit_btn = btn
                        break
                except Exception:
                    continue

        if not submit_btn:
            log.warning("❌ 未找到提交按钮，跳过审批")
            screenshot(page, "approve_no_submit_btn")
            return False

        submit_btn.click()
        wait(page, 2000)

        # 处理确认弹窗
        try:
            confirm_btn = None
            for selector in ["button:has-text('确定')", "button:has-text('确 定')"]:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=1000):
                        confirm_btn = btn
                        break
                except Exception:
                    pass
            if not confirm_btn:
                for frame in page.frames:
                    for selector in ["button:has-text('确定')", "button:has-text('确 定')"]:
                        try:
                            btn = frame.locator(selector).first
                            if btn.is_visible(timeout=2000):
                                confirm_btn = btn
                                break
                        except Exception:
                            pass
                    if confirm_btn:
                        break
            if confirm_btn:
                confirm_btn.click()
            else:
                page.once("dialog", lambda dialog: dialog.accept())
        except Exception as e:
            log.warning(f"确认弹窗处理失败: {e}")

        wait(page, 3000)
        log.info("✅ 模块4：审批完成")
        return True

    except Exception as e:
        log.error(f"❌ 模块4（流程审批）执行异常: {e}")
        log.debug(traceback.format_exc())
        screenshot(page, "module4_approve_error")
        full_cleanup(page)
        return False

# =====================================================================
# ========================  邮件通知（v3）=============================
# =====================================================================
def send_result_email(results: list):
    total   = len(results)
    success = sum(results)
    if not CONFIG["sender_email"] or not CONFIG["recipient_email"]:
        log.info("📧 邮件未配置，跳过发送")
        return
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
# ===============  模块级重试包装器（v3 精华）==========================
# =====================================================================
def retry_module(func, page, module_name: str):
    """
    模块级重试（v3 核心机制）。
    重试前自动清理弹窗、移除遮罩层、回到首页。
    """
    max_retries = CONFIG["max_retries"]
    delay = CONFIG["retry_delay"]

    for attempt in range(1, max_retries + 1):
        try:
            result = func(page)
            if isinstance(result, str):
                return result
            if result:
                return True
            else:
                log.warning(f"⚠️ {module_name} 第{attempt}/{max_retries}次尝试返回 False")
        except Exception as e:
            log.warning(f"⚠️ {module_name} 第{attempt}/{max_retries}次尝试异常: {e}")

        if attempt < max_retries:
            log.info(f"🔄 {delay}秒后重试 {module_name}...")
            full_cleanup(page)
            safe_go_home(page)
            time.sleep(delay)

    log.error(f"❌ {module_name} 重试{max_retries}次后仍然失败，跳过")
    return False

# =====================================================================
# ========================  主循环（v3 精华）===========================
# =====================================================================
def run_one_cycle(page, cycle_num: int, total_cycles: int) -> bool:
    """执行一次完整的业务循环（模块2→3→4），返回是否全部成功"""
    log.info(f"\n{'='*55}\n第 {cycle_num}/{total_cycles} 次循环开始 [{cycle_num/total_cycles*100:.1f}%]\n{'='*55}")
    update_status(cycle_num, total_cycles, "开始", f"第 {cycle_num}/{total_cycles} 次循环")

    if not safe_go_home(page):
        log.error(f"第 {cycle_num} 次循环：无法回到首页，跳过")
        update_status(cycle_num, total_cycles, "回到首页", "失败")
        return False

    results = {}

    # 模块2：添加收文
    if CONFIG["run_module2"]:
        update_status(cycle_num, total_cycles, "模块2-添加收文", "执行中...")
        mod2_result = retry_module(add_receive_document, page, "模块2-添加收文")
        if mod2_result == "skip_to_module3":
            log.info("⚡ 模块2返回 skip_to_module3，直接进入模块3")
            results["模块2-添加收文"] = True
        elif not mod2_result:
            log.warning("⏭️ 模块2失败，跳过模块3和模块4")
            update_status(cycle_num, total_cycles, "模块2-添加收文", "失败（已跳过）")
            return False
        else:
            results["模块2-添加收文"] = True
    else:
        log.info("⏭️ 模块2已关闭，跳过")
        results["模块2-添加收文"] = True

    # 模块3：启动流程
    if CONFIG["run_module3"]:
        update_status(cycle_num, total_cycles, "模块3-启动流程", "执行中...")
        results["模块3-启动流程"] = retry_module(start_workflow, page, "模块3-启动流程")
        if not results["模块3-启动流程"]:
            log.warning("⏭️ 模块3失败，跳过模块4")
            update_status(cycle_num, total_cycles, "模块3-启动流程", "失败（已跳过）")
            return False
    else:
        log.info("⏭️ 模块3已关闭，跳过")
        results["模块3-启动流程"] = True

    # 模块4：流程审批
    if CONFIG["run_module4"]:
        update_status(cycle_num, total_cycles, "模块4-流程审批", "执行中...")
        results["模块4-流程审批"] = retry_module(approve_workflow, page, "模块4-流程审批")
        if not results["模块4-流程审批"]:
            log.warning("⏭️ 模块4失败")
            update_status(cycle_num, total_cycles, "模块4-流程审批", "失败（已跳过）")
            return False
    else:
        log.info("⏭️ 模块4已关闭，跳过")
        results["模块4-流程审批"] = True

    status = "✅ 全部完成"
    update_status(cycle_num, total_cycles, status, f"成功 | {results}")
    log.info(f"{status} | 第 {cycle_num} 次循环 | {results}")
    return True

# =====================================================================
# ========================  主函数（v3 + v5 增强）======================
# =====================================================================
def main():
    ensure_dir(CONFIG["screenshot_dir"])
    log.info("🤖 OA 自动化脚本 v5.0 启动")
    log.info(f"📋 配置: 循环{CONFIG['repeat_count']}次 | "
             f"模块2={'ON' if CONFIG['run_module2'] else 'OFF'} | "
             f"模块3={'ON' if CONFIG['run_module3'] else 'OFF'} | "
             f"模块4={'ON' if CONFIG['run_module4'] else 'OFF'} | "
             f"无头={'ON' if CONFIG['headless'] else 'OFF'}")
    if OCR_AVAILABLE:
        log.info("🔤 验证码自动识别已启用 (ddddocr)")
    else:
        log.info("⚠️ 验证码自动识别未启用（未安装 ddddocr），登录时将提示手动输入")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"])

        if os.path.exists(CONFIG["auth_file"]):
            context = browser.new_context(storage_state=CONFIG["auth_file"])
        else:
            context = browser.new_context()

        page = context.new_page()
        page.set_default_timeout(CONFIG["timeout_default"])
        page.goto(CONFIG["home_url"])

        # 检查并确保登录
        if not is_logged_in(page):
            log.warning("⚠️ Session 已失效或不存在，触发登录流程...")
            if CONFIG["headless"]:
                log.info("🔄 切换到有窗口模式以完成验证码登录...")
                page.close()
                context.close()
                browser.close()
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(CONFIG["timeout_default"])
                page.goto(CONFIG["home_url"])

            if not captcha_login_with_retry(page):
                log.error("登录失败，脚本退出")
                browser.close()
                return

            # 登录成功后切回原模式
            if CONFIG["headless"]:
                log.info("🔄 登录完成，切回无头模式继续执行...")
                page.close()
                context.close()
                browser.close()
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(storage_state=CONFIG["auth_file"])
                page = context.new_page()
                page.set_default_timeout(CONFIG["timeout_default"])
                page.goto(CONFIG["home_url"])
        else:
            log.info("✅ 已通过 auth.json 自动登录")

        # ==================== 主循环（v3：失败跳过不终止）====================
        results = []
        total = CONFIG["repeat_count"]
        skipped = 0

        for i in range(1, total + 1):
            ok = run_one_cycle(page, i, total)
            results.append(ok)
            if not ok:
                skipped += 1
                log.warning(f"⏭️ 第 {i}/{total} 次循环未完全成功，跳过并继续下一次")
            else:
                log.info(f"📊 当前进度: {i}/{total} ({i/total*100:.1f}%) | 成功 {sum(results)}/{i}")
            wait(page, 2000)

        success_count = sum(results)
        log.info(f"\n🎉 全部循环执行完毕！共 {len(results)} 次，成功 {success_count} 次，"
                 f"失败/跳过 {len(results) - success_count} 次")

        context.close()
        browser.close()

        finalize_status(results)

    send_result_email(results)

if __name__ == "__main__":
    main()
