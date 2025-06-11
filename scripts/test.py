import requests
import json
from datetime import datetime, timedelta

# --- (辅助类和配置保持不变) ---
ACCOUNT_ID = "U18665565" # 请使用您的账户ID
BASE_URL = "https://localhost:5000/v1/api"
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def query_and_calculate_pnl_amount():
    """
    最终版:
    1. 获取每日资产净值(NAV)和累计TWR。
    2. 计算每日TWR，并用它乘以昨日NAV，得出不受出入金影响的每日绝对盈亏金额。
    3. 以表格形式打印最近30天的每日绝对盈亏金额。
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

        # --- 3. 解析并计算每日绝对盈亏金额 ---
        
        # 定位并提取NAV和TWR所需的数据
        nav_data_root = data['nav']
        cps_data_root = data['cps']
        account_nav_details = nav_data_root['data'][0]
        account_cps_details = cps_data_root['data'][0]
        
        nav_values = account_nav_details['navs']
        nav_dates = nav_data_root['dates']
        
        cumulative_twr_values = account_cps_details['returns']
        twr_dates = cps_data_root['dates']
        
        currency = account_nav_details.get("baseCurrency", "USD")

        # 校验数据
        if len(nav_values) != len(nav_dates) or len(cumulative_twr_values) != len(twr_dates) or len(nav_dates) != len(twr_dates):
            raise ValueError("API响应中的NAV或TWR数据列表长度不匹配。")

        # 创建历史数据字典
        full_history_nav = dict(zip(nav_dates, nav_values))
        full_history_cumulative_twr = dict(zip(twr_dates, cumulative_twr_values))
        
        # 计算每日绝对盈亏金额
        daily_pnl_amount = {}
        sorted_dates = sorted(full_history_nav.keys())
        
        for i in range(1, len(sorted_dates)):
            today_date_str = sorted_dates[i]
            yesterday_date_str = sorted_dates[i-1]
            
            # 获取计算所需的数据
            nav_yesterday = full_history_nav[yesterday_date_str]
            twr_today_cumulative = full_history_cumulative_twr[today_date_str]
            twr_yesterday_cumulative = full_history_cumulative_twr[yesterday_date_str]
            
            # 计算每日TWR
            daily_twr_value = (1 + twr_today_cumulative) / (1 + twr_yesterday_cumulative + 1e-9) - 1
            
            # 计算纯净盈亏金额
            pnl_amount = daily_twr_value * nav_yesterday
            daily_pnl_amount[today_date_str] = pnl_amount

        # 筛选最近30天
        today = datetime.now()
        start_date = today - timedelta(days=30)
        
        filtered_pnl = {date: pnl for date, pnl in daily_pnl_amount.items() 
                        if start_date.date() <= datetime.strptime(date, "%Y%m%d").date() <= today.date()}

        # --- 4. 打印格式化结果 ---
        if not filtered_pnl:
            print(f"\n{Colors.YELLOW}在过去30天内未找到任何每日盈亏记录。{Colors.RESET}")
            return

        print(f"\n{Colors.CYAN}{Colors.BOLD}--- 账户 {ACCOUNT_ID} 最近30天每日投资表现 (绝对金额) ---{Colors.RESET}")
        print(f"+{'-'*16}+{'-'*25}+")
        print(f"| {'日期':^14} | {'当日涨跌 ({})'.format(currency):^23} |")
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
        print(f"| {'总计涨跌':^14} | {Colors.BOLD}{total_color}{total_pnl_str:>20}{Colors.RESET}   |")
        print(f"+{'-'*16}+{'-'*25}+")

    except Exception as e:
        print(f"\n{Colors.RED}❌ 发生错误: {e}{Colors.RESET}")

if __name__ == "__main__":
    query_and_calculate_pnl_amount()