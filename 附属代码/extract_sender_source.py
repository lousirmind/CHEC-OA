# extract_sender_source.py
import re
import csv
from collections import defaultdict
from playwright.sync_api import sync_playwright

# ================== 模块1：登录（复用原逻辑） ==================
def do_login(page, username="your-username", password="your-password"):
    """登录系统，验证码手动输入"""
    print("🔐 开始登录...")
    page.goto("http://your-oa-server.com/cloudoa/login")
    page.get_by_placeholder("请输入用户名").fill(username)
    page.get_by_placeholder("请输入密码").fill(password)

    captcha_input = page.get_by_role("textbox", name="验证码")
    captcha_input.scroll_into_view_if_needed()
    captcha_input.click()

    print("👀 请查看浏览器窗口，手动输入验证码，然后按回车键继续...")
    input("✅ 输入完成后按回车键 --> ")

    page.get_by_role("button", name="登 录").click()
    page.get_by_title("邮件管理").wait_for(state="visible", timeout=15000)
    print("✅ 登录成功")
    return True

def is_logged_in(page):
    try:
        page.get_by_title("邮件管理").wait_for(state="visible", timeout=5000)
        return True
    except:
        return False

# ================== 翻页辅助函数 ==================
def click_next_page(frame, page):
    """点击下一页按钮，返回是否成功"""
    next_btn = frame.locator("div.layui-table-page").get_by_text(">", exact=True)
    if next_btn.count() == 0:
        next_btn = frame.locator("div.layui-table-page").get_by_text("下一页", exact=True)
    if next_btn.count() == 0:
        next_btn = frame.locator("a.layui-laypage-next")
    if next_btn.count() == 0:
        return False
    if next_btn.get_attribute("class") and "disabled" in next_btn.get_attribute("class"):
        return False
    next_btn.click()
    page.wait_for_timeout(2000)
    frame.locator("tbody tr").first.wait_for(state="attached", timeout=5000)
    return True

def get_column_index_by_text(frame, header_text):
    """根据表头文本获取列索引（从0开始）"""
    headers = frame.locator("thead tr th").all_text_contents()
    # 去除空白字符
    headers = [h.strip() for h in headers]
    for idx, h in enumerate(headers):
        if header_text in h:
            return idx
    return -1

def extract_sender_and_source(frame):
    """从当前页提取所有邮件的 (发件人, 来源) 元组列表"""
    rows = frame.locator("tbody tr").all()
    # 先获取列索引
    sender_idx = get_column_index_by_text(frame, "发件人")
    source_idx = get_column_index_by_text(frame, "来源")
    if sender_idx == -1 or source_idx == -1:
        print("⚠️ 未找到发件人或来源列，请检查表头文字")
        return []
    
    data = []
    for row in rows:
        cells = row.locator("td").all()
        if len(cells) <= max(sender_idx, source_idx):
            continue
        sender = cells[sender_idx].inner_text().strip()
        source = cells[source_idx].inner_text().strip()
        if sender and source:  # 过滤空值
            data.append((sender, source))
    return data

# ================== 主函数 ==================
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        page.goto("http://your-oa-server.com/cloudoa/")
        if not is_logged_in(page):
            print("⚠️ 未检测到登录状态，将执行手动登录...")
            if not do_login(page):
                print("登录失败，退出")
                return
        else:
            print("✅ 已通过 auth.json 自动登录")

        # 进入公共邮箱
        page.get_by_title("邮件管理").click()
        page.get_by_text("公共邮箱").click()

        mail_frame = page.frame_locator("iframe").first
        # 设置每页显示90条（可选）
        mail_frame.get_by_role("combobox").select_option("90")
        page.wait_for_timeout(2000)

        # 统计字典： (发件人, 来源) -> 出现次数
        counter = defaultdict(int)
        current_page = 1
        max_pages = 20  # 防止无限循环

        while current_page <= max_pages:
            print(f"📄 正在处理第 {current_page} 页...")
            page_data = extract_sender_and_source(mail_frame)
            for sender, source in page_data:
                counter[(sender, source)] += 1
            print(f"   本页提取 {len(page_data)} 条记录")

            # 尝试翻页
            if not click_next_page(mail_frame, page):
                print("🏁 已到达最后一页")
                break
            current_page += 1
            # 重新获取 iframe 引用（页面刷新后定位器可能失效）
            mail_frame = page.frame_locator("iframe").first
            page.wait_for_timeout(1000)

        # 生成 CSV 文件
        csv_file = "sender_source_mapping.csv"
        with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["序号", "发信人", "来源", "编号模板", "数量"])
            for idx, ((sender, source), count) in enumerate(counter.items(), start=1):
                writer.writerow([idx, sender, source, "", count])

        print(f"✅ 统计完成！共 {len(counter)} 个唯一组合，已保存至 {csv_file}")

        context.close()
        browser.close()

if __name__ == "__main__":
    main()