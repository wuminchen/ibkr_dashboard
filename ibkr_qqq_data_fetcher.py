from ib_insync import *
import pandas as pd
import datetime
import time
from tqdm.auto import tqdm
import pytz # 导入 pytz

# 定义时区
us_eastern = pytz.timezone('US/Eastern')
utc = pytz.utc # UTC 时区

# 连接到 IB Gateway 或 TWS
ib = IB()
print("尝试连接到 IB Gateway/TWS...")
try:
    ib.connect('127.0.0.1', 7496, clientId=30)
    print("成功连接到 IB Gateway/TWS。")
except Exception as e:
    print(f"连接失败: {e}")
    print("请确保 IB Gateway 或 TWS 正在运行，并且 API 端口已启用。")
    exit()

# 定义 QQQ 合约
contract = Stock('QQQ', 'SMART', 'USD')

# 定义起始日期和结束日期，并将其设置为时区感知 (UTC)
end_date = datetime.datetime.now(utc)
start_date = end_date - datetime.timedelta(days=5 * 365) # 往前推 5 年

# 存储所有历史数据的列表
all_bars = []

# 定义每次请求的时间段
duration_per_request = '1 D' # 每次请求 1 天的数据

current_end_date = end_date

print(f"开始获取 QQQ 1分钟历史数据，从 {start_date.strftime('%Y-%m-%d %H:%M %Z')} 到 {end_date.strftime('%Y-%m-%d %H:%M %Z')}...")

# 估算总共需要多少次请求以设置进度条的迭代次数
total_days = (end_date - start_date).days
estimated_iterations = total_days + 1

# 使用 tqdm 创建进度条，并使用 bar_format 自定义外观
custom_bar_format = '{desc}: {percentage:.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'

with tqdm(total=estimated_iterations, desc="数据获取中", bar_format=custom_bar_format) as pbar:
    while current_end_date > start_date:
        if current_end_date > datetime.datetime.now(utc):
            current_end_date = datetime.datetime.now(utc)

        pbar.set_description(f"获取数据 (截止到 {current_end_date.strftime('%Y-%m-%d %H:%M %Z')})")

        try:
            end_dt_str_for_ib = current_end_date.astimezone(us_eastern).strftime('%Y%m%d %H:%M:%S') + ' US/Eastern'

            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end_dt_str_for_ib,
                durationStr=duration_per_request,
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )

            if not bars:
                print(f"\n警告: 在 {current_end_date.strftime('%Y-%m-%d %H:%M %Z')} 之前没有更多数据，可能已获取到起始日期或无交易数据。")
                current_end_date = current_end_date - datetime.timedelta(days=1)
                pbar.update(1)
                time.sleep(5)
                continue

            # --- 实时打印获取到的数据摘要 ---
            if bars: # 确保 bars 列表非空
                # pbar.write() 用于在进度条上方打印内容，避免进度条被覆盖
                pbar.write(f"  > 获取到 {len(bars)} 条 K 线，日期范围：")
                pbar.write(f"    - 起始：{bars[0].date.strftime('%Y-%m-%d %H:%M:%S')} O:{bars[0].open} H:{bars[0].high} L:{bars[0].low} C:{bars[0].close} V:{bars[0].volume}")
                pbar.write(f"    - 结束：{bars[-1].date.strftime('%Y-%m-%d %H:%M:%S')} O:{bars[-1].open} H:{bars[-1].high} L:{bars[-1].low} C:{bars[-1].close} V:{bars[-1].volume}")
            # --- 实时打印结束 ---

            new_current_end_date_utc = bars[0].date.astimezone(utc)
            all_bars = bars + all_bars
            current_end_date = new_current_end_date_utc
            pbar.update(1)
            time.sleep(10)

        except Exception as e:
            print(f"\n获取数据时发生错误: {e}")
            time.sleep(30)
            current_end_date = current_end_date - datetime.timedelta(days=1)
            continue

# 将数据转换为 Pandas DataFrame
if all_bars:
    df = util.df(all_bars)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')
    df.index = df.index.tz_convert(utc)
    df = df[df.index >= start_date]

    print(f"\n成功获取 {len(df)} 条 QQQ 1分钟K线数据。")
    print(df.head())
    print(df.tail())

    output_filename = 'QQQ_5_year_1_minute_data.csv'
    df.to_csv(output_filename)
    print(f"数据已保存到 {output_filename}")
else:
    print("\n未能获取到任何 QQQ 历史数据。")

# 断开连接
ib.disconnect()
print("已断开与 IB API 的连接。")