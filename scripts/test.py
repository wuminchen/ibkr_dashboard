import requests
import json
from datetime import datetime, timedelta

# --- 1. 用户配置 ---
# ⚠️ 请将 'U18665565' 替换为您的真实 IBKR 账户号
ACCOUNT_ID = "U18665565"  # 我从您的数据中看到了这个ID，如果不对请修改
# Client Portal Gateway 的地址和端口
BASE_URL = "https://localhost:5000/v1/api"

# 定义用于在终端打印颜色的类
class Colors:
    GREEN = '\033[92m'   # 绿色，用于盈利
    RED = '\033[91m'     # 红色，用于亏损
    YELLOW = '\033[93m'  # 黄色，用于警告或总计
    CYAN = '\03C96m'    # 青色，用于标题
    BOLD = '\033[1m'     # 加粗
    RESET = '\033[0m'    # 重置所有格式

def query_and_print_pnl_formatted():
    """
    查询并以美观的、带颜色的表格格式打印最近30天的每日盈亏。
    此版本已适配将日期和盈亏值分为两个独立列表的API响应格式。
    """
    endpoint = "/pa/performance"
    url = BASE_URL + endpoint
    payload = {"acctIds": [ACCOUNT_ID], "freq": "D"}

    print(f"正在查询账户 {ACCOUNT_ID} 的历史表现数据...")

    try:
        response = requests.post(url, verify=False, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        print("数据获取成功，正在处理...")

        # --- 3. 解析和过滤数据 (*** 这是修改的核心部分 ***) ---
        
        # 检查账户数据是否存在
        if ACCOUNT_ID not in data or "pnl" not in data[ACCOUNT_ID]:
            print(f"{Colors.RED}错误: API响应中未找到账户 {ACCOUNT_ID} 的盈亏(P&L)数据。{Colors.RESET}")
            return

        pnl_data = data[ACCOUNT_ID]["pnl"]

        # 检查新的数据结构是否存在
        if "nav" not in pnl_data or "dates" not in pnl_data:
            print(f"{Colors.RED}错误: 未找到 'nav' 或 'dates' 列表，数据格式不匹配。{Colors.RESET}")
            return

        pnl_values = pnl_data["nav"]
        date_strings = pnl_data["dates"]
        currency = data[ACCOUNT_ID].get("baseCurrency", "USD")

        # 检查两个列表的长度是否一致，确保数据可以配对
        if len(pnl_values) != len(date_strings):
            print(f"{Colors.RED}错误: 盈亏数据和日期列表的长度不匹配！{Colors.RESET}")
            return
            
        # 使用 zip 将两个列表合并为一个日期:盈亏的字典
        all_daily_pnl = dict(zip(date_strings, pnl_values))
        
        # 后续的过滤逻辑保持不变
        today = datetime.now()
        start_date = today - timedelta(days=30)
        
        filtered_pnl = {}
        for date_str, pnl_value in all_daily_pnl.items():
            pnl_date = datetime.strptime(date_str, "%Y%m%d")
            if start_date.date() <= pnl_date.date() <= today.date():
                filtered_pnl[date_str] = pnl_value

        # --- 4. 以美化的表格格式打印结果 (此部分无需改动) ---
        if not filtered_pnl:
            print(f"\n{Colors.YELLOW}在过去30天内未找到任何盈亏记录。{Colors.RESET}")
            return

        # (打印逻辑与之前完全相同)
        print(f"\n{Colors.CYAN}{Colors.BOLD}--- 账户 {ACCOUNT_ID} 最近30天每日盈亏 ({currency}) ---{Colors.RESET}")
        print(f"+{'-'*16}+{'-'*25}+")
        print(f"| {'日期':^14} | {'当日盈亏':^23} |")
        print(f"+{'-'*16}+{'-'*25}+")

        total_pnl = 0
        for date_str in sorted(filtered_pnl.keys()):
            pnl_value = filtered_pnl[date_str]
            total_pnl += pnl_value
            display_date = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
            pnl_str = f"{pnl_value:,.2f}"
            color = Colors.GREEN if pnl_value > 0 else Colors.RED if pnl_value < 0 else Colors.RESET
            print(f"|  {display_date}  | {color}{pnl_str:>20}{Colors.RESET}   |")

        print(f"+{'-'*16}+{'-'*25}+")
        total_pnl_str = f"{total_pnl:,.2f}"
        total_color = Colors.GREEN if total_pnl > 0 else Colors.RED if total_pnl < 0 else Colors.RESET
        print(f"| {'总计盈亏':^14} | {Colors.BOLD}{total_color}{total_pnl_str:>20}{Colors.RESET}   |")
        print(f"+{'-'*16}+{'-'*25}+")

    except requests.exceptions.RequestException as e:
        print(f"\n{Colors.RED}❌ 连接错误: 请确保 Client Portal Gateway 正在运行并已登录。{Colors.RESET}")
    except Exception as e:
        print(f"\n{Colors.RED}❌ 发生未知错误: {e}{Colors.RESET}")

if __name__ == "__main__":
    query_and_print_pnl_formatted()