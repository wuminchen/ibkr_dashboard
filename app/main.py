# app/main.py (最终版: 允许局域网访问，并手动打开浏览器)

import requests
import pandas as pd
from flask import Flask, render_template, jsonify, request as flask_request, redirect, url_for, Response
import json
import sys
import os
import subprocess
import time
import platform
import concurrent.futures

# --- 应用程序配置 ---
app = Flask(__name__)

# 定义项目根目录, 以便正确找到 templates 和 vendor 文件夹
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 使用项目根目录来定位 templates 文件夹
app.template_folder = os.path.join(PROJECT_ROOT, 'templates')

BASE_URL = "https://localhost:5000/v1/api/"
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


# --- 核心功能函数 ---

def is_gateway_running():
    """检查网关是否已连接并认证"""
    try:
        response = requests.get(f"{BASE_URL}iserver/auth/status", verify=False, timeout=2)
        return response.status_code == 200 and response.json().get('connected')
    except requests.exceptions.RequestException:
        return False

def start_gateway():
    """启动IBKR网关, 使用其内部的默认配置文件"""
    print(">>> 正在尝试自动启动 IBKR Gateway...")
    
    gateway_path = os.path.join(PROJECT_ROOT, 'vendor', 'clientportal.gw')
    
    if not os.path.isdir(gateway_path):
        print(f"!!! 错误：在项目目录下未找到 'vendor/clientportal.gw' 文件夹: {gateway_path}")
        return False

    if platform.system() == "Windows":
        run_script = os.path.join(gateway_path, 'bin', 'run.bat')
        conf_file_argument = 'root\\conf.yaml'
        flags = subprocess.CREATE_NEW_CONSOLE
    else:
        run_script = os.path.join(gateway_path, 'bin', 'run.sh')
        conf_file_argument = 'root/conf.yaml'
        flags = 0

    if not os.path.exists(run_script):
        print(f"!!! 错误: 启动脚本未找到: {run_script}")
        return False
        
    try:
        subprocess.Popen([run_script, conf_file_argument], cwd=gateway_path, creationflags=flags)
        print(">>> ✅ 网关启动命令已发送。请等待其初始化。")
        return True
    except Exception as e:
        print(f"!!! 自动启动网关失败: {e}")
        return False

def get_all_account_ids():
    """获取所有账户ID"""
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
    """获取单个账户的摘要信息"""
    try:
        response = requests.get(f"{BASE_URL}portfolio/{account_id}/summary", verify=False, timeout=10)
        return response.json() if response.status_code == 200 else {}
    except requests.exceptions.RequestException:
        return {}
        
def get_account_positions(account_id):
    """获取单个账户的持仓信息"""
    try:
        response = requests.get(f"{BASE_URL}portfolio/{account_id}/positions/0", verify=False, timeout=10)
        return response.json() if response.status_code == 200 else []
    except requests.exceptions.RequestException:
        return []

def get_price_snapshots(conids):
    """批量获取合约的价格快照"""
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

def aggregate_portfolio_data(all_data):
    """汇总所有账户的数据"""
    aggregated_summary = {
        'net_liquidation': 0, 'realized_pnl': 0, 'cash': 0,
        'buying_power': 0, 'currency': 'USD' 
    }
    aggregated_positions = {}
    if not all_data:
        return {'summary': aggregated_summary, 'positions': []}

    for account_id, data in all_data.items():
        if not data or not data.get('summary'): continue

        aggregated_summary['net_liquidation'] += data['summary']['net_liquidation']
        aggregated_summary['realized_pnl'] += data['summary']['realized_pnl']
        aggregated_summary['cash'] += data['summary']['cash']
        aggregated_summary['buying_power'] += data['summary']['buying_power']
        aggregated_summary['currency'] = data['summary']['currency']

        for pos in data['positions']:
            conid, position_size, cost_basis = pos['conid'], float(pos.get('position', 0)), float(pos.get('costBasis', 0))
            if conid not in aggregated_positions:
                aggregated_positions[conid] = pos.copy()
                aggregated_positions[conid]['total_position'] = 0
                aggregated_positions[conid]['total_costBasis'] = 0
                aggregated_positions[conid]['holdings_breakdown'] = {}
            
            aggregated_positions[conid]['total_position'] += position_size
            aggregated_positions[conid]['total_costBasis'] += cost_basis
            aggregated_positions[conid]['holdings_breakdown'][account_id] = position_size

    final_positions = []
    for conid, pos in aggregated_positions.items():
        total_pos, total_cb = pos['total_position'], pos['total_costBasis']
        pos['position'], pos['costBasis'] = total_pos, total_cb
        pos['avgCost'] = total_cb / total_pos if total_pos != 0 else 0
        final_positions.append(pos)
        
    return {'summary': aggregated_summary, 'positions': final_positions}    

def fetch_account_data(acc_id):
    """获取并处理单个账户的摘要和持仓数据"""
    print(f"--> 开始获取账户 {acc_id} 的数据...")
    summary_raw = get_account_summary(acc_id)
    positions_raw = get_account_positions(acc_id)
    
    processed_positions = []
    if isinstance(positions_raw, list):
        for p in positions_raw:
            try:
                p['costBasis'] = float(p.get('position', 0)) * float(p.get('avgCost', 0))
                processed_positions.append(p)
            except (ValueError, TypeError):
                p['costBasis'] = 0
                processed_positions.append(p)

    summary_data = {
        key: float(summary_raw.get(val, {}).get('amount', 0)) 
        for key, val in [
            ('net_liquidation', 'netliquidation'), 
            ('realized_pnl', 'realizedpnl'), 
            ('cash', 'cashbalance'), 
            ('buying_power', 'buyingpower')
        ]
    }
    summary_data['currency'] = summary_raw.get('netliquidation', {}).get('currency', 'USD')
    
    print(f"<-- 完成获取账户 {acc_id} 的数据。")
    return acc_id, {'summary': summary_data, 'positions': processed_positions}

# --- Flask 路由 ---
@app.route('/favicon.ico')
def favicon():
    """处理浏览器对favicon.ico的请求，避免404错误"""
    return Response(status=204)

@app.route('/')
def home():
    """主页，使用并发加载所有账户数据并展示"""
    print("\n--- 正在并行加载所有账户数据... ---")
    start_time = time.time()
    
    account_ids = get_all_account_ids()
    if not account_ids:
        print(">>> 警告: 未能获取到任何账户ID。可能需要重新认证。")
        return render_template('login.html', error="获取账户信息失败，请在弹窗中重新登录。")

    all_data = {}
    max_workers = min(len(account_ids), 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_account = {executor.submit(fetch_account_data, acc_id): acc_id for acc_id in account_ids}
        for future in concurrent.futures.as_completed(future_to_account):
            acc_id = future_to_account[future]
            try:
                _, data = future.result()
                all_data[acc_id] = data
            except Exception as exc:
                print(f"!!! 获取账户 {acc_id} 数据时产生异常: {exc}")
                all_data[acc_id] = None
    
    aggregated_data = aggregate_portfolio_data(all_data)
    
    end_time = time.time()
    print(f"--- ✅ 所有数据加载完毕，总耗时: {end_time - start_time:.2f} 秒 ---")
    
    return render_template('index.html', all_data=all_data, aggregated_data=aggregated_data)

@app.route('/api/prices')
def api_prices():
    """提供给前端的API，用于动态获取价格"""
    conids_str = flask_request.args.get('conids', '')
    if not conids_str: 
        return jsonify({})
        
    conids = conids_str.split(',')
    raw_price_data = get_price_snapshots(conids)
    
    price_dict = {}
    for conid in conids:
        data = raw_price_data.get(conid)
        if data:
            price = data.get('31', 'N/A')
            is_closing_price = isinstance(price, str) and price.startswith('C')
            price_dict[conid] = {
                'price': price[1:] if is_closing_price else price,
                'change': data.get('83', 'N/A'),
                'is_close': is_closing_price
            }
    return jsonify(price_dict)

@app.route('/login')
def login_page():
    """登录页面，如果已认证则直接跳转主页"""
    print(">>> 正在检查网关认证状态...")
    if is_gateway_running():
        print(">>> ✅ 网关已认证，直接跳转至主仪表盘。")
        return redirect(url_for('home'))
    else:
        print(">>> ⚠️ 网关未认证，显示登录页面。")
        return render_template('login.html')

@app.route('/api/check_auth')
def check_auth_status():
    """提供给前端的API，用于轮询认证状态"""
    if is_gateway_running():
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'pending'})

# --- 主程序入口 ---
if __name__ == '__main__':
    print("="*40)
    print(" 启动 IBKR 实时报告应用 ".center(40, "="))
    print("="*40)
    
    if not is_gateway_running():
        start_gateway()
        print(">>> 等待网关初始化 (约10-15秒)...")
        time.sleep(10)

    print("\n>>> ✅ Flask Web 服务器已成功启动。")
    print(">>> ➡️  请在浏览器中手动访问以下地址:")
    print(">>>    - 本机访问: http://127.0.0.1:8000/login")
    print(">>>    - 局域网访问: http://<您电脑的IP地址>:8000/login")
    
    try:
        # --- 主要改动在这里：将 host 设置为 '0.0.0.0' ---
        app.run(host='0.0.0.0', port=8000, debug=False)
    except OSError as e:
        print(f"!!! 启动 Web 服务器失败: {e}")
        print("!!! 端口 8000 可能已被占用。")