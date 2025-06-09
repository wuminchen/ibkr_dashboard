# app.py (优化后版本)

import requests
import pandas as pd
from flask import Flask, render_template, jsonify, request as flask_request, redirect, url_for
import json
import sys
import os
import subprocess
import time
import platform
from datetime import datetime, timedelta
import webbrowser
import threading

# --- 应用程序配置 ---
app = Flask(__name__)
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
BASE_URL = "https://localhost:5000/v1/api/"
# 禁用 InsecureRequestWarning 警告
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


# --- 核心功能函数 (与之前相同) ---
def is_gateway_running():
    """检查网关认证状态"""
    try:
        response = requests.get(f"{BASE_URL}iserver/auth/status", verify=False, timeout=2)
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
        # 使用 Popen 在后台启动网关进程
        subprocess.Popen([run_script, conf_file], cwd=gateway_path, creationflags=flags)
        print(">>> ✅ 网关启动命令已发送。请等待其初始化。")
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
        params = {'conids': ','.join(conids), 'fields': '31,83'} # 31=最后价, 83=日涨跌
        response = requests.get(endpoint_url, params=params, verify=False, timeout=5)
        if response.status_code == 200:
            return {str(item.get('conid')): item for item in response.json()}
        return {}
    except requests.exceptions.RequestException:
        return {}

def aggregate_portfolio_data(all_data):
    """聚合所有账户的数据，生成一个统一的视图。"""
    aggregated_summary = {
        'net_liquidation': 0, 'realized_pnl': 0, 'cash': 0,
        'buying_power': 0, 'currency': 'USD' 
    }
    aggregated_positions = {}
    if not all_data:
        return {'summary': aggregated_summary, 'positions': []}

    for account_id, data in all_data.items():
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

# --- Flask 路由 ---
@app.route('/')
def home():
    """主仪表盘页面"""
    print("\n--- 正在加载主页数据... ---")
    account_ids = get_all_account_ids()
    if not account_ids:
        print(">>> 警告: 未能获取到任何账户ID。可能需要重新认证。")
        # 如果获取不到账户信息，重定向到登录页
        return render_template('login.html', error="获取账户信息失败，请在弹窗中重新登录。")

    all_data = {}
    for acc_id in account_ids:
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

        all_data[acc_id] = {
            'summary': { key: float(summary_raw.get(val, {}).get('amount', 0)) for key, val in [('net_liquidation', 'netliquidation'), ('realized_pnl', 'realizedpnl'), ('cash', 'cashbalance'), ('buying_power', 'buyingpower')] },
            'positions': processed_positions
        }
        all_data[acc_id]['summary']['currency'] = summary_raw.get('netliquidation', {}).get('currency', 'USD')
    
    aggregated_data = aggregate_portfolio_data(all_data)
    return render_template('index.html', all_data=all_data, aggregated_data=aggregated_data)

@app.route('/api/prices')
def api_prices():
    """提供给前端的价格更新API"""
    conids_str = flask_request.args.get('conids', '')
    if not conids_str: 
        return jsonify({})
        
    # --- 修改开始 ---
    # 1. 首先，创建 conids 列表
    conids = conids_str.split(',')
    # 2. 然后，将创建好的 conids 传递给函数
    raw_price_data = get_price_snapshots(conids)
    # --- 修改结束 ---
    
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
# --- 新增的路由 ---
@app.route('/login')
def login_page():
    """
    智能登录入口：
    - 如果网关已认证，直接重定向到主页。
    - 如果未认证，才显示等待登录页面。
    """
    print(">>> 正在检查网关认证状态...")
    if is_gateway_running():
        print(">>> ✅ 网关已认证，直接跳转至主仪表盘。")
        # 使用 redirect 和 url_for 直接跳转到 home() 函数对应的路由 ('/')
        return redirect(url_for('home'))
    else:
        print(">>> ⚠️ 网关未认证，显示登录页面。")
        # 网关未连接，按原流程显示等待页面，让前端JS去处理
        return render_template('login.html')

@app.route('/api/check_auth')
def check_auth_status():
    """供前端调用的API，用于检查网关是否已认证"""
    if is_gateway_running():
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'pending'})

# --- 主程序入口 ---
def open_browser():
      """延迟一秒后打开浏览器，确保服务器已启动"""
      webbrowser.open_new("http://127.0.0.1:8000/login")

if __name__ == '__main__':
    print("="*40)
    print(" 启动 IBKR 实时报告应用 ".center(40, "="))
    print("="*40)
    
    # 无论如何都先尝试启动一次网关
    # 如果已在运行，这个操作是无害的
    if not is_gateway_running():
        start_gateway()
        print(">>> 等待网关初始化 (约10-15秒)...")
        time.sleep(10) # 留出时间给网关进程启动

    print("\n>>> ✅ Flask Web 服务器已启动。")
    print(">>> ➡️  正在为您打开浏览器...")
    print(">>> ➡️  请在弹出的 IBKR 页面中完成登录认证。")
    print(">>> ➡️  登录成功后，本应用页面将自动刷新。")
    
    # 使用线程计时器，在Flask服务器启动1秒后打开浏览器
    threading.Timer(1, open_browser).start()
    
    try:
        # 运行Flask应用，关闭调试模式以获得更稳定的体验
        app.run(host='127.0.0.1', port=8000, debug=False)
    except OSError as e:
        print(f"!!! 启动 Web 服务器失败: {e}")
        print("!!! 端口 8000 可能已被占用。")