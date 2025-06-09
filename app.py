import requests
import pandas as pd
from flask import Flask, render_template, jsonify, request as flask_request
import json
import sys
import os
import subprocess
import time
import platform
from datetime import datetime, timedelta

# --- 应用程序配置 ---
app = Flask(__name__)
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
BASE_URL = "https://localhost:5000/v1/api/"
requests.packages.urllib3.disable_warnings()


# --- 核心功能函数 ---
def is_gateway_running():
    """检查网关认证状态"""
    try:
        response = requests.get(f"{BASE_URL}iserver/auth/status", verify=False, timeout=3)
        return response.status_code == 200 and response.json().get('connected')
    except requests.exceptions.RequestException:
        return False

def start_gateway():
    """尝试自动启动网关"""
    print(">>> 正在尝试自动启动 IBKR Gateway...")
    project_root = os.path.dirname(os.path.abspath(__file__))
    gateway_path = os.path.join(project_root, 'clientportal.gw')
    if not os.path.isdir(gateway_path):
        print(f"!!! 错误：在项目目录下未找到 'clientportal.gw' 文件夹: {gateway_path}")
        return False
    if platform.system() == "Windows":
        run_script, conf_file = os.path.join(gateway_path, 'bin', 'run.bat'), 'root\\conf.yaml'
        flags = subprocess.CREATE_NEW_CONSOLE
    else:
        run_script, conf_file = os.path.join(gateway_path, 'bin', 'run.sh'), 'root/conf.yaml'
        flags = 0
    if not os.path.exists(run_script):
        print(f"!!! 错误: 启动脚本未找到: {run_script}")
        return False
    try:
        subprocess.Popen([run_script, conf_file], cwd=gateway_path, creationflags=flags)
        print(">>> ✅ 网关启动命令已发送。")
        return True
    except Exception as e:
        print(f"!!! 自动启动网关失败: {e}")
        return False

def get_all_account_ids():
    """获取所有真实的账户ID列表。"""
    try:
        response = requests.get(f"{BASE_URL}portfolio/accounts", verify=False, timeout=5)
        if response.status_code == 200:
            accounts_data = response.json()
            if isinstance(accounts_data, list):
                return [acc.get('accountId') for acc in accounts_data if acc.get('accountId')]
            return []
        return None
    except requests.exceptions.RequestException:
        return None

def get_account_summary(account_id):
    """获取指定账户的摘要信息"""
    try:
        response = requests.get(f"{BASE_URL}portfolio/{account_id}/summary", verify=False, timeout=5)
        return response.json() if response.status_code == 200 else {}
    except requests.exceptions.RequestException:
        return {}
        
def get_account_positions(account_id):
    """获取账户的详细持仓列表"""
    try:
        response = requests.get(f"{BASE_URL}portfolio/{account_id}/positions/0", verify=False, timeout=5)
        return response.json() if response.status_code == 200 else []
    except requests.exceptions.RequestException:
        return []

def get_price_snapshots(conids):
    """获取价格快照"""
    if not conids: return {}
    try:
        endpoint_url = f"{BASE_URL}md/snapshot"
        params = {'conids': ','.join(conids), 'fields': '31,83'}
        response = requests.get(endpoint_url, params=params, verify=False, timeout=5)
        if response.status_code == 200:
            return {str(item.get('conid')): item for item in response.json()}
        return {}
    except requests.exceptions.RequestException:
        return {}
# --- 新增的辅助函数：聚合投资组合数据 ---
def aggregate_portfolio_data(all_data):
    """聚合所有账户的数据，生成一个统一的视图。"""
    aggregated_summary = {
        'net_liquidation': 0,
        'realized_pnl': 0,
        'cash': 0,
        'buying_power': 0,
        'currency': 'USD' # 假设所有账户货币相同
    }
    # 使用 conid 作为 key 来聚合持仓
    aggregated_positions = {}

    if not all_data:
        return {'summary': aggregated_summary, 'positions': []}

    # 1. 遍历所有账户，累加摘要和持仓信息
    for account_id, data in all_data.items():
        aggregated_summary['net_liquidation'] += data['summary']['net_liquidation']
        aggregated_summary['realized_pnl'] += data['summary']['realized_pnl']
        aggregated_summary['cash'] += data['summary']['cash']
        aggregated_summary['buying_power'] += data['summary']['buying_power']
        # 你可以把 currency 设置为基础货币
        aggregated_summary['currency'] = data['summary']['currency']

        for pos in data['positions']:
            conid = pos['conid']
            position_size = float(pos.get('position', 0))
            cost_basis = float(pos.get('costBasis', 0))

            if conid not in aggregated_positions:
                # 如果是第一次遇到这个conid，初始化它
                aggregated_positions[conid] = pos.copy() # 复制基础信息
                aggregated_positions[conid]['total_position'] = 0
                aggregated_positions[conid]['total_costBasis'] = 0
                aggregated_positions[conid]['holdings_breakdown'] = {}
            
            # 累加数据
            aggregated_positions[conid]['total_position'] += position_size
            aggregated_positions[conid]['total_costBasis'] += cost_basis
            aggregated_positions[conid]['holdings_breakdown'][account_id] = position_size

    # 2. 计算最终的聚合值（如加权平均成本）
    final_positions = []
    for conid, pos in aggregated_positions.items():
        total_pos = pos['total_position']
        total_cb = pos['total_costBasis']
        
        # 替换原始值为聚合值
        pos['position'] = total_pos
        pos['costBasis'] = total_cb
        if total_pos != 0:
            pos['avgCost'] = total_cb / total_pos
        else:
            pos['avgCost'] = 0
        
        final_positions.append(pos)
        
    return {'summary': aggregated_summary, 'positions': final_positions}    

# --- Flask 路由 ---
@app.route('/')
def home():
    print("\n--- 正在加载主页数据... ---")
    account_ids = get_all_account_ids()
    if not account_ids:
        print(">>> 警告: 未能获取到任何账户ID。")
        return render_template('index.html', all_data={}, aggregated_data=None)

    all_data = {}
    for acc_id in account_ids:
        summary_raw = get_account_summary(acc_id)
        positions_raw = get_account_positions(acc_id)
        
        processed_positions = []
        if isinstance(positions_raw, list):
            for p in positions_raw:
                try:
                    position_size = float(p.get('position', 0))
                    avg_cost = float(p.get('avgCost', 0))
                    p['costBasis'] = position_size * avg_cost
                    processed_positions.append(p)
                except (ValueError, TypeError):
                    p['costBasis'] = 0
                    processed_positions.append(p)

        all_data[acc_id] = {
            'summary': { 'net_liquidation': float(summary_raw.get('netliquidation', {}).get('amount', 0)), 'realized_pnl': float(summary_raw.get('realizedpnl', {}).get('amount', 0)), 'cash': float(summary_raw.get('cashbalance', {}).get('amount', 0)), 'buying_power': float(summary_raw.get('buyingpower', {}).get('amount', 0)), 'currency': summary_raw.get('netliquidation', {}).get('currency', 'USD') },
            'positions': processed_positions
        }
    
    # --- 新增：调用聚合函数 ---
    aggregated_data = aggregate_portfolio_data(all_data)

    # 将原始数据和聚合后的数据都传递给模板
    return render_template('index.html', all_data=all_data, aggregated_data=aggregated_data)

@app.route('/api/prices')
def api_prices():
    conids_str = flask_request.args.get('conids', '')
    if not conids_str: return jsonify({})
        
    conids = conids_str.split(',')
    raw_price_data = get_price_snapshots(conids)
    
    price_dict = {}
    for conid in conids:
        data = raw_price_data.get(conid)
        if data:
            price = data.get('31', 'N/A')
            is_closing_price = False
            if isinstance(price, str) and price.startswith('C'):
                price = price[1:]
                is_closing_price = True

            price_dict[conid] = {
                'price': price,
                'change': data.get('83', 'N/A'),
                'is_close': is_closing_price
            }
    return jsonify(price_dict)


# --- 主程序入口 ---
if __name__ == '__main__':
    print("="*40)
    print(" 启动 IBKR 实时报告应用 ".center(40, "="))
    print("="*40)
    
    # 启动检查等... (保持不变)
    if not is_gateway_running():
        print(">>> ⚠️ 未检测到正在运行的 IBKR Gateway。")
        if not start_gateway(): sys.exit(1)
        print(">>> 正在等待网关初始化 (约15秒)...")
        time.sleep(15)
    
    print("\n" + "!"*55)
    print("!!  请确保您已在浏览器中完成 IBKR 登录认证！ !!")
    print("!"*55 + "\n")

    if not is_gateway_running():
        print(">>> ❌ 登录超时或网关未能成功启动。")
        sys.exit(1)

    print("\n>>> ✅ 网关已就绪！正在启动 Flask Web 服务器...")
    print(">>> ➡️  请在浏览器中打开 http://127.0.0.1:8000")
    try:
        app.run(host='127.0.0.1', port=8000, debug=False) # 建议关闭debug模式
    except OSError as e:
        print(f"!!! 启动 Web 服务器失败: {e}")