# app/main.py (最终版: 初始加载时预取所有数据)

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
import datetime

# --- 应用程序配置 ---
app = Flask(__name__)

# 定义项目根目录, 以便正确找到 templates 和 vendor 文件夹
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 使用项目根目录来定位 templates 文件夹
app.template_folder = os.path.join(PROJECT_ROOT, 'templates')

BASE_URL = "https://localhost:5000/v1/api/"
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# 全局变量用于缓存历史表现数据
performance_cache = {}


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

def get_historical_performance(account_id):
    """获取并计算账户基于时间加权回报率(TWR)的真实每日投资表现"""
    global performance_cache
    cache_duration_minutes = 15

    if account_id in performance_cache:
        cached_data = performance_cache[account_id]
        time_since_cache = datetime.datetime.now() - cached_data['timestamp']
        if time_since_cache < datetime.timedelta(minutes=cache_duration_minutes):
            print(f"--> [Cache HIT] 返回账户 {account_id} 的历史表现缓存数据。")
            return cached_data['data']

    print(f"--> [Cache MISS] 正在为账户 {account_id} 调用 /pa/performance API 获取TWR数据...")

    try:
        endpoint_url = f"{BASE_URL}pa/performance"
        payload = {'acctIds': [account_id]}
        response = requests.post(endpoint_url, json=payload, verify=False, timeout=20)
        response.raise_for_status()
        data = response.json()

        cps_data_root = data.get('cps', {})
        account_data_node = cps_data_root.get('data', [{}])[0]
        cumulative_returns = account_data_node.get('returns', [])
        date_strings = cps_data_root.get('dates', [])

        if not cumulative_returns or not date_strings or len(cumulative_returns) != len(date_strings):
            raise ValueError("API响应中CPS或日期数据不完整或不匹配。")

        daily_twr_list = []
        sorted_returns = sorted(zip(date_strings, cumulative_returns))

        for i in range(1, len(sorted_returns)):
            current_date, cumulative_today = sorted_returns[i]
            _, cumulative_yesterday = sorted_returns[i-1]
            daily_twr = (1 + cumulative_today) / (1 + cumulative_yesterday) - 1
            daily_twr_list.append({'date': current_date, 'twr': daily_twr})

        performance_cache[account_id] = {'timestamp': datetime.datetime.now(), 'data': daily_twr_list}
        print(f"<-- 完成获取和处理账户 {account_id} 的每日TWR数据。")
        return daily_twr_list
    except (requests.exceptions.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"!!! 获取或处理账户 {account_id} 的历史表现数据时出错: {e}")
        return None

# main.py

def fetch_all_data_for_account(acc_id):
    """获取并处理单个账户的摘要、持仓和历史表现数据"""
    
    # --- 新增的防御性检查 ---
    if not acc_id or not acc_id.strip():
        print(f"!!! 检测到无效的账户ID，已跳过。ID: '{acc_id}'")
        # 返回一个空的数据结构，以避免下游函数出错
        return acc_id, {'summary': {}, 'positions': [], 'performance': None}
    # --- 检查结束 ---

    print(f"--> 开始并行获取账户 {acc_id} 的所有数据...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_summary = executor.submit(get_account_summary, acc_id)
        future_positions = executor.submit(get_account_positions, acc_id)
        future_performance = executor.submit(get_historical_performance, acc_id)

        summary_raw = future_summary.result()
        positions_raw = future_positions.result()
        performance_data = future_performance.result()

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
    return acc_id, {'summary': summary_data, 'positions': processed_positions, 'performance': performance_data}
    """获取并处理单个账户的摘要、持仓和历史表现数据"""
    print(f"--> 开始并行获取账户 {acc_id} 的所有数据...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_summary = executor.submit(get_account_summary, acc_id)
        future_positions = executor.submit(get_account_positions, acc_id)
        future_performance = executor.submit(get_historical_performance, acc_id)

        summary_raw = future_summary.result()
        positions_raw = future_positions.result()
        performance_data = future_performance.result()

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
    return acc_id, {'summary': summary_data, 'positions': processed_positions, 'performance': performance_data}

def aggregate_portfolio_data(all_data):
    """汇总所有账户的数据"""
    aggregated_summary = {'net_liquidation': 0, 'realized_pnl': 0, 'cash': 0, 'buying_power': 0, 'currency': 'USD'}
    aggregated_positions = {}
    if not all_data: return {'summary': aggregated_summary, 'positions': []}

    for account_id, data in all_data.items():
        if not data or not data.get('summary'): continue
        for key in ['net_liquidation', 'realized_pnl', 'cash', 'buying_power']:
            aggregated_summary[key] += data['summary'].get(key, 0)
        aggregated_summary['currency'] = data['summary'].get('currency', 'USD')

        for pos in data.get('positions', []):
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
@app.route('/favicon.ico')
def favicon():
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
    historical_data = {}

    max_workers = min(len(account_ids), 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_account = {executor.submit(fetch_all_data_for_account, acc_id): acc_id for acc_id in account_ids}
        for future in concurrent.futures.as_completed(future_to_account):
            acc_id = future_to_account[future]
            try:
                _, data = future.result()
                historical_data[acc_id] = data.pop('performance', None)
                all_data[acc_id] = data
            except Exception as exc:
                print(f"!!! 获取账户 {acc_id} 数据时产生异常: {exc}")
                all_data[acc_id] = None
                historical_data[acc_id] = None
    
    aggregated_data = aggregate_portfolio_data(all_data)
    
    end_time = time.time()
    print(f"--- ✅ 所有数据加载完毕，总耗时: {end_time - start_time:.2f} 秒 ---")
    
    historical_data_json = json.dumps(historical_data)
    return render_template('index.html', 
                           all_data=all_data, 
                           aggregated_data=aggregated_data,
                           historical_data_json=historical_data_json)

@app.route('/api/prices')
def api_prices():
    """提供给前端的API，用于动态获取价格"""
    conids_str = flask_request.args.get('conids', '')
    if not conids_str: return jsonify({})
        
    conids = conids_str.split(',')
    raw_price_data = get_price_snapshots(conids)
    
    price_dict = {}
    for conid in conids:
        data = raw_price_data.get(conid)
        if data:
            price = data.get('31', 'N/A')
            is_closing_price = isinstance(price, str) and price.startswith('C')
            price_dict[conid] = {'price': price[1:] if is_closing_price else price, 'change': data.get('83', 'N/A')}
    return jsonify(price_dict)

@app.route('/login')
def login_page():
    """登录页面，如果已认证则直接跳转主页"""
    if is_gateway_running():
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/api/check_auth')
def check_auth_status():
    """提供给前端的API，用于轮询认证状态"""
    return jsonify({'status': 'success' if is_gateway_running() else 'pending'})

# --- 主程序入口 ---
if __name__ == '__main__':
    print("="*40 + "\n" + " 启动 IBKR 实时报告应用 ".center(40, "=") + "\n" + "="*40)
    
    if not is_gateway_running():
        start_gateway()
        print(">>> 等待网关初始化 (约10-15秒)...")
        time.sleep(15)

    print("\n>>> ✅ Flask Web 服务器已成功启动。")
    print(">>> ➡️  请在浏览器中手动访问以下地址:")
    print(">>>    - 本机访问: http://127.0.0.1:8000/login")
    print(">>>    - 局域网访问: http://<您电脑的IP地址>:8000/login")
    
    try:
        app.run(host='0.0.0.0', port=8000, debug=False)
    except OSError as e:
        print(f"!!! 启动 Web 服务器失败: {e}\n!!! 端口 8000 可能已被占用。")