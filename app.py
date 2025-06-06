import requests
import pandas as pd
from flask import Flask, render_template, jsonify, request as flask_request
import json
import sys
import os
import subprocess
import time
import platform

# --- 应用程序配置 ---
app = Flask(__name__)
BASE_URL = "https://localhost:5000/v1/api/"
requests.packages.urllib3.disable_warnings()


# --- 核心功能函数 ---
def is_gateway_running():
    try:
        response = requests.get(f"{BASE_URL}iserver/auth/status", verify=False, timeout=3)
        return response.status_code == 200 and response.json().get('connected')
    except requests.exceptions.RequestException:
        return False

def start_gateway():
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

# ----------------- vvvvvvvv 最终核心修正 vvvvvvvv -----------------
def get_all_account_ids():
    """获取所有真实的账户ID列表。改用 /portfolio/accounts 接口以提高兼容性。"""
    try:
        # 使用 /portfolio/accounts 端点，它返回的是一个包含账户对象的列表
        response = requests.get(f"{BASE_URL}portfolio/accounts", verify=False, timeout=5)
        
        # 增加调试打印，看看这个接口返回了什么
        print(f">>> 调试信息: /portfolio/accounts 接口返回状态码: {response.status_code}")
        
        if response.status_code == 200:
            accounts_data = response.json()
            print(f">>> 调试信息: /portfolio/accounts 原始响应: {json.dumps(accounts_data, indent=2)}")
            
            # 从对象列表中提取 'accountId'
            if isinstance(accounts_data, list):
                # 确保 accountId 存在才提取
                return [acc.get('accountId') for acc in accounts_data if acc.get('accountId')]
            return []
        return None # 如果状态码不为200，则返回None表示有问题
    except requests.exceptions.RequestException:
        return None # 连接层面的错误也返回None
# ----------------- ^^^^^^^^ 最终核心修正 ^^^^^^^^ -----------------


def get_account_positions(account_id):
    try:
        response = requests.get(f"{BASE_URL}portfolio/{account_id}/positions", verify=False, timeout=5)
        return response.json() if response.status_code == 200 else []
    except requests.exceptions.RequestException:
        return []

def get_price_snapshots(conids):
    if not conids: return {}
    try:
        response = requests.post(f"{BASE_URL}md/snapshot", verify=False, json={'conids': conids}, timeout=5)
        return {str(item.get('conid')): item for item in response.json()} if response.status_code == 200 else {}
    except requests.exceptions.RequestException:
        return {}


# --- Flask 路由 ---
@app.route('/')
def home():
    print("\n--- 正在加载主页数据... ---")
    account_ids = get_all_account_ids()
    # 如果get_all_account_ids返回None，我们给一个空列表以防出错
    if account_ids is None:
        account_ids = []

    all_positions = {}
    for acc_id in account_ids:
        positions = get_account_positions(acc_id)
        all_positions[acc_id] = [{'conid': p.get('conid'), 'contractDesc': p.get('contractDesc'), 'position': p.get('position', 0), 'avgCost': p.get('avgCost', 0)} for p in positions]
    
    # 增加一个检查，如果最终还是没有数据，在模板中可以显示提示
    if not all_positions:
         print(">>> 警告: 未能获取任何账户的持仓数据，页面将显示为空。")

    return render_template('index.html', all_positions=all_positions)

@app.route('/api/prices')
def api_prices():
    conids_str = flask_request.args.get('conids', '')
    raw_price_data = get_price_snapshots(conids_str.split(','))
    price_dict = {conid: data.get('31', 'N/A') for conid, data in raw_price_data.items()}
    return jsonify(price_dict)


# --- 主程序入口 ---
if __name__ == '__main__':
    print("="*40)
    print(" 启动 IBKR 实时报告应用 ".center(40, "="))
    print("="*40)
    
    # 启动前检查
    print(">>> 正在执行启动前检查...")
    if not is_gateway_running():
        print(">>> ⚠️ 未检测到正在运行的 IBKR Gateway。")
        if not start_gateway():
            sys.exit(1)
        
        print(">>> 正在等待网关初始化 (约15秒)...")
        time.sleep(15)
    
    print("\n" + "!"*55)
    print("!!  请确保您已在浏览器中完成 IBKR 登录认证！ !!")
    print("!!  如果仍然失败，请尝试手动进行“再认证”(Re-authenticate) !!")
    print("!"*55 + "\n")

    # 再次检查认证状态
    if not is_gateway_running():
        print(">>> ❌ 登录超时或网关未能成功启动。请手动启动网关后重试。")
        sys.exit(1)

    print("\n>>> ✅ 网关已就绪！正在启动 Flask Web 服务器...")
    print(">>> ➡️  请在浏览器中打开 http://127.0.0.1:8000")
    try:
        app.run(host='127.0.0.1', port=8000, debug=False)
    except OSError as e:
        print(f"!!! 启动 Web 服务器失败: {e}")