import xml.etree.ElementTree as ET
from collections import defaultdict

def analyze_flex_report_monthly(filename="Realized_PL_Report.xml"):
    """
    解析从IBKR下载的Flex Query XML报告，
    按月份汇总并计算总的已实现盈亏。
    """
    try:
        tree = ET.parse(filename)
        root = tree.getroot()
        
        # 使用 defaultdict 可以让代码更简洁，当一个月份第一次出现时，自动创建默认值
        monthly_summary = defaultdict(lambda: {'pnl': 0.0, 'commission': 0.0, 'trade_count': 0})

        # 找到所有的Trade节点
        for trade in root.findall('.//Trade'):
            realized_pl_str = trade.get('fifoPnlRealized')
            
            # 我们只关心有已实现盈亏的平仓交易
            if realized_pl_str and float(realized_pl_str) != 0:
                # 提取日期和月份
                datetime_str = trade.get('dateTime')
                # 日期格式是 YYYY-MM-DD;HHMMSS，我们取前7个字符作为月份的键，例如 "2025-03"
                month_key = datetime_str[:7].replace('-', '') # 兼容 YYYY-MM-DD 和 YYYYMMDD
                month_key = f"{month_key[:4]}-{month_key[4:6]}" # 统一格式为 YYYY-MM

                pnl = float(realized_pl_str)
                commission = 0.0
                commission_str = trade.get('ibCommission')
                if commission_str:
                    commission = float(commission_str)
                
                # 累加到对应月份的统计中
                monthly_summary[month_key]['pnl'] += pnl
                monthly_summary[month_key]['commission'] += commission
                monthly_summary[month_key]['trade_count'] += 1

        # --- 开始打印分析结果 ---
        print("\n--- Flex报告分析结果 (按月) ---")
        print(f"报告文件: {filename}")
        print("-" * 55)
        print(f"{'月份':<10} | {'平仓次数':<10} | {'月度总盈亏 (Gross)':<20} | {'月度净盈亏 (Net)':<20}")
        print("-" * 55)

        # 按月份排序并打印
        total_net_pl = 0
        sorted_months = sorted(monthly_summary.keys())
        for month in sorted_months:
            data = monthly_summary[month]
            net_pnl = data['pnl'] + data['commission']
            total_net_pl += net_pnl
            
            pnl_str = f"{data['pnl']:>12,.2f}"
            net_pnl_str = f"{net_pnl:>12,.2f}"
            
            print(f"{month:<10} | {data['trade_count']:<10} | {pnl_str:<20} | {net_pnl_str:<20}")

        print("-" * 55)
        print(f"报告期内总净已实现盈亏: {total_net_pl:,.2f} USD")
        print("-" * 55)


    except FileNotFoundError:
        print(f"!!! 错误: 找不到文件 '{filename}'。请确保Python脚本和XML文件在同一个目录下。")
    except ET.ParseError as e:
        print(f"!!! 错误: XML文件格式不正确，无法解析。 {e}")
    except Exception as e:
        print(f"!!! 发生未知错误: {e}")

# --- 主程序入口 ---
if __name__ == '__main__':
    analyze_flex_report_monthly()