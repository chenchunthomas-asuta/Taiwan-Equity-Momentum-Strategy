import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import os
from tqdm import tqdm
from datetime import datetime
from fugle_marketdata import RestClient
import warnings
warnings.filterwarnings('ignore')

# =========================================================
# 區塊一：核心參數與 JSON 讀寫路徑
# =========================================================
API_KEY = "YOUR_FUGLE_API_KEY"  # ⚠️ 請填入你的富果 API KEY

CONFIG_PATH = os.path.expanduser("~/quant_fund/portfolio.json")

# 🔥 資金與交易成本設定 (V7.9.4 法人規格)
INITIAL_TOTAL_CAPITAL = 100000000 # 1億台幣
FEE_DISCOUNT = 0.28
FEE_RATE = 0.001425 * FEE_DISCOUNT
TAX_RATE = 0.003
SLIPPAGE = 0.002
TODAY_STR = datetime.now().strftime("%Y-%m-%d")

# =========================================================
# V7.9.4 核心參數 (機構級濾網與動態權重)
# =========================================================
MAX_INDIVIDUAL_WEIGHT = 0.20    # 單檔最高權重 20%
TARGET_EXPOSURE = 0.85          # 預計總多頭曝險 85% (留 15% 現金作為防禦緩衝)
LIQUIDITY_PARTICIPATION = 0.10  # 流動性天花板：最高吃下 20日均量的 10%
EXIT_RANK_THRESHOLD = 40        # 動能退潮二階死線清倉閥值 

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(capital, portfolio, cash):
    config_data = {
        "TOTAL_CAPITAL": capital,
        "CASH_BALANCE": cash,
        "my_portfolio": portfolio
    }
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

# =========================================================
# 區塊二：市場資料與報價抓取
# =========================================================
def get_all_taiwan_stocks():
    tickers, stock_names = [], {}
    try:
        res_twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10).json()
        for item in res_twse:
            if len(item.get('Code', '')) == 4 and item['Code'].isdigit():
                tickers.append(f"{item['Code']}.TW")
                stock_names[f"{item['Code']}.TW"] = item['Name'].strip()
        res_tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", timeout=10).json()
        for item in res_tpex:
            if len(item.get('SecuritiesCompanyCode', '')) == 4 and item['SecuritiesCompanyCode'].isdigit():
                tickers.append(f"{item['SecuritiesCompanyCode']}.TWO")
                stock_names[f"{item['SecuritiesCompanyCode']}.TWO"] = item['CompanyName'].strip()
    except: pass
    
    # 強制覆蓋特定股票名稱
    stock_names["8150.TW"] = "南茂"
    stock_names["8046.TW"] = "南電"
    
    return list(set(tickers)), stock_names

def get_realtime_price(symbol, client):
    if client is None or API_KEY == "YOUR_FUGLE_API_KEY": return None
    try:
        quote = client.stock.intraday.quote(symbol=symbol.split('.')[0])
        return quote.get('lastPrice')
    except: return None

def tw_round(price):
    if price < 10: return round(price, 2)
    elif price < 50: return round(price * 20) / 20
    elif price < 100: return round(price * 10) / 10
    elif price < 500: return round(price * 2) / 2
    elif price < 1000: return round(price)
    else: return round(price / 5) * 5

# =========================================================
# 區塊三：V7.9.4 執行引擎
# =========================================================
def execute_pipeline():
    print(f"=== 主動動能台股增長 ETF (V7.9.4 法人規格版) ===")

    config = load_config()
    if not config: 
        print("尚未建立 portfolio.json，將以初始資金啟動。")
        TOTAL_CAPITAL = INITIAL_TOTAL_CAPITAL
        my_portfolio = {}
        current_cash = TOTAL_CAPITAL
    else:
        TOTAL_CAPITAL = config.get("TOTAL_CAPITAL", INITIAL_TOTAL_CAPITAL)
        my_portfolio = config.get("my_portfolio", {})
        current_cash = config.get("CASH_BALANCE", TOTAL_CAPITAL)

    fugle_client = RestClient(api_key=API_KEY) if API_KEY != "YOUR_FUGLE_API_KEY" else None
    all_tickers, stock_names = get_all_taiwan_stocks()
    all_tickers = list(set(all_tickers + list(my_portfolio.keys())))

    # 階段 1：大盤多空判斷 (大盤濾網：0050 必須 > SMA60)
    df_market = yf.download("0050.TW", period="1y", progress=False)
    if isinstance(df_market.columns, pd.MultiIndex): df_market.columns = df_market.columns.get_level_values(0)
    market_is_bull = df_market['Close'].iloc[-1] > df_market['Close'].rolling(60).mean().iloc[-1]
    
    try:
        # 這裡的 inception date 可以依據你的實盤啟動日做更改
        inception_date = "2024-01-01" 
        market_inception_price = df_market.loc[:inception_date]['Close'].iloc[-1]
        market_itd_ret = (df_market['Close'].iloc[-1] - market_inception_price) / market_inception_price * 100
    except:
        market_itd_ret = 0.0

    # 階段 2：全市場動能海選與特徵工程
    data = yf.download(all_tickers, period="1y", group_by='ticker', threads=False, progress=False)
    stock_metrics = {}
    old_weights = {}
    
    old_shares_dict = {ticker: pos['shares'] for ticker, pos in my_portfolio.items()}
    
    yesterday_nav = current_cash
    for t, pos in my_portfolio.items():
        yesterday_nav += pos['shares'] * pos['cost']
    
    for ticker in tqdm(all_tickers, desc="計算截面動能與流動性"):
        try:
            df = data[ticker].dropna(how='all')
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            if len(df) < 125: continue
            
            rt_px = get_realtime_price(ticker, fugle_client)
            close = rt_px if rt_px else df['Close'].iloc[-1]
            
            mom_120 = (close / df['Close'].iloc[-120]) - 1
            sma5 = df['Close'].rolling(5).mean().iloc[-1]
            sma20 = df['Close'].rolling(20).mean().iloc[-1]
            
            daily_ret = df['Close'].pct_change()
            vol_20 = daily_ret.rolling(20).std().iloc[-1]
            turnover = df['Close'] * df['Volume']
            adv_20 = turnover.rolling(20).mean().iloc[-1]
            
            stock_metrics[ticker] = {
                'Close': close, 'Mom_120': mom_120, 'SMA5': sma5, 'SMA20': sma20, 
                'Vol_20': vol_20, 'ADV_20': adv_20
            }
            
            if ticker in my_portfolio:
                old_weights[ticker] = (my_portfolio[ticker]['shares'] * close) / yesterday_nav * 100
        except: continue

    df_rank = pd.DataFrame(stock_metrics).T
    df_targets = pd.DataFrame()
    
    if not df_rank.empty:
        df_rank['Rank'] = df_rank['Mom_120'].rank(ascending=False)
        
        # ---------------------------------------------------------
        # 🎯 V7.9.4 核心計算：機構級濾網與動態目標權重
        # ---------------------------------------------------------
        # 一階個股濾網：前 20 名、ADV_20 > 5,000萬台幣、價格 > 20日均線
        candidates_mask = (df_rank['Rank'] <= 20) & (df_rank['ADV_20'] > 50000000) & (df_rank['Close'] > df_rank['SMA20'])
        df_targets = df_rank[candidates_mask].copy()
        
        if not df_targets.empty:
            # 階梯乘數 (Rank Multiplier)
            df_targets['Rank_Mult'] = np.where(df_targets['Rank'] <= 5, 1.5,
                                      np.where(df_targets['Rank'] <= 10, 1.0, 0.5))
            
            # 波動度倒數 (Inverse Volatility)
            df_targets['Vol_20'] = df_targets['Vol_20'].replace(0, 0.001)
            df_targets['Raw_Weight'] = (1.0 / df_targets['Vol_20']) * df_targets['Rank_Mult']
            
            # 歸一化並套用目標曝險 (Target Exposure: 85%)
            df_targets['Norm_Weight'] = (df_targets['Raw_Weight'] / df_targets['Raw_Weight'].sum()) * TARGET_EXPOSURE
            
            # 計算 10% 流動性天花板權重
            df_targets['Liq_Cap_Weight'] = (df_targets['ADV_20'] * LIQUIDITY_PARTICIPATION) / yesterday_nav
            
            # 融合決策：取最小值，且單檔不超過 20%
            df_targets['Target_Weight'] = df_targets[['Norm_Weight', 'Liq_Cap_Weight']].min(axis=1)
            df_targets['Target_Weight'] = df_targets['Target_Weight'].clip(upper=MAX_INDIVIDUAL_WEIGHT)

    # 階段 3：出場風控與狀態機減碼
    new_portfolio = {}
    tg_actions = []
    current_market_value = 0

    for ticker, pos in my_portfolio.items():
        name = stock_names.get(ticker, ticker.split('.')[0])
        if ticker in stock_metrics:
            metrics = stock_metrics[ticker]
            rank = df_rank.loc[ticker, 'Rank'] if not df_rank.empty else 999
            
            # 【二階死線】大盤轉空、跌破月線、或動能大幅衰退 -> 100% 全部出清
            if (not market_is_bull) or (metrics['Close'] < metrics['SMA20']) or (rank > EXIT_RANK_THRESHOLD):
                sell_val = pos['shares'] * metrics['Close'] * (1 - FEE_RATE - TAX_RATE - SLIPPAGE)
                current_cash += sell_val
                pnl = ((metrics['Close'] / pos['cost']) - 1) * 100
                tg_actions.append(f"賣出：{name}({ticker}) (二階死線：全部出清) | 損益: {pnl:+.2f}%")
            
            # 【一階警報】高檔洗盤跌破 5MA -> 減碼 50% 保本
            elif metrics['Close'] < metrics['SMA5'] and not pos.get('reduced', False):
                sell_shares = int((pos['shares'] * 0.5) / 1000) * 1000 
                
                if sell_shares > 0:
                    sell_val = sell_shares * metrics['Close'] * (1 - FEE_RATE - TAX_RATE - SLIPPAGE)
                    current_cash += sell_val
                    pnl = ((metrics['Close'] / pos['cost']) - 1) * 100
                    
                    pos['shares'] -= sell_shares
                    pos['reduced'] = True  
                    new_portfolio[ticker] = pos
                    current_market_value += pos['shares'] * metrics['Close']
                    tg_actions.append(f"賣出：{name}({ticker}) (一階警報：50% 減碼) | 損益: {pnl:+.2f}%")
                else:
                    pos['reduced'] = True 
                    new_portfolio[ticker] = pos
                    current_market_value += pos['shares'] * metrics['Close']
            else:
                if metrics['Close'] >= metrics['SMA5']:
                    pos['reduced'] = False 
                new_portfolio[ticker] = pos
                current_market_value += pos['shares'] * metrics['Close']
        else:
            new_portfolio[ticker] = pos
            current_market_value += pos['shares'] * pos['cost']

    # 階段 4：V7.9.4 融合動態權重建倉與加碼
    if market_is_bull and not df_targets.empty:
        current_nav_est = current_cash + current_market_value
        
        for ticker, row in df_targets.sort_values('Rank').iterrows():
            target_weight = row['Target_Weight']
            target_value = current_nav_est * target_weight
            
            if ticker in new_portfolio:
                pos = new_portfolio[ticker]
                if pos.get('reduced', False): 
                    continue
                current_val = pos['shares'] * row['Close']
            else:
                current_val = 0
            
            if target_value > current_val and current_cash > 0:
                budget = target_value - current_val
                max_affordable_cost = min(current_cash, budget)
                
                true_price_with_fee = row['Close'] * (1 + FEE_RATE + SLIPPAGE)
                add_shares = int((max_affordable_cost / true_price_with_fee) / 1000) * 1000
                
                if add_shares > 0:
                    cost = add_shares * true_price_with_fee
                    current_cash -= cost
                    current_market_value += add_shares * row['Close']
                    
                    name = stock_names.get(ticker, ticker.split('.')[0])
                    
                    if ticker in new_portfolio:
                        old_shares = new_portfolio[ticker]['shares']
                        old_cost = new_portfolio[ticker]['cost']
                        
                        new_portfolio[ticker]['shares'] += add_shares
                        new_portfolio[ticker]['cost'] = ((old_shares * old_cost) + cost) / new_portfolio[ticker]['shares']
                        tg_actions.append(f"買進：{name}({ticker}) (動態加碼) | 成交價: {tw_round(row['Close'])}")
                    else:
                        new_portfolio[ticker] = {
                            "cost": true_price_with_fee, 
                            "shares": add_shares, 
                            "date": TODAY_STR, 
                            "reduced": False
                        }
                        tg_actions.append(f"買進：{name}({ticker}) (動態新倉) | 成交價: {tw_round(row['Close'])}")

    # 階段 5：報表格式產出
    final_nav = current_cash + current_market_value
    save_config(final_nav, new_portfolio, current_cash)
    
    fund_itd_ret = (final_nav - INITIAL_TOTAL_CAPITAL) / INITIAL_TOTAL_CAPITAL * 100
    alpha = fund_itd_ret - market_itd_ret

    tg_holdings = []
    for ticker, pos in new_portfolio.items():
        name = stock_names.get(ticker, ticker.split('.')[0])
        px = stock_metrics[ticker]['Close'] if ticker in stock_metrics else pos['cost']
        weight = (pos['shares'] * px) / final_nav * 100
        old_w = old_weights.get(ticker, 0.0)
        
        old_shares = old_shares_dict.get(ticker, 0)
        current_shares = pos['shares']
        w_diff_str = f"{weight - old_w:+.2f}%"
        
        action_str = ""
        if old_shares == 0:
            action_str = " (新倉)"
        elif current_shares > old_shares:
            action_str = f" ({w_diff_str} 加碼)"
        elif current_shares < old_shares:
            action_str = f" ({w_diff_str} 減碼)"
        else:
            action_str = f" ({w_diff_str})"
            
        pnl = ((px / pos['cost']) - 1) * 100
            
        tg_holdings.append({
            "text": f"{name}({ticker}): {weight:.2f}%{action_str} | 報酬率: {pnl:+.2f}%",
            "weight": weight
        })

    tg_holdings_sorted = [x['text'] for x in sorted(tg_holdings, key=lambda x: x['weight'], reverse=True)]

    try:
        # 推播設定
        TG_TOKEN = "" # ⚠️ 請填寫你的 Telegram Bot Token
        TG_CHAT_ID = "" # ⚠️ 請填寫你的 Telegram Chat ID
        
        if TG_TOKEN != "":
            report_msg = f"""【V7.9.4 動態權重結算報告】
日期：{TODAY_STR}

初始投入本金：{INITIAL_TOTAL_CAPITAL:,.0f} 元
當前總淨資產：{final_nav:,.0f} 元
最終市場曝險：{(current_market_value/final_nav*100):.2f}%
最終剩餘現金：{current_cash:,.0f} 元

本基金累積報酬率：{fund_itd_ret:.2f}%
同期大盤對標報酬：{market_itd_ret:.2f}%
超額報酬 (Alpha)：{alpha:+.2f}%

【今日買賣操作】
"""
            if tg_actions: report_msg += "\n".join(tg_actions) + "\n\n"
            else: report_msg += "今日無任何買賣操作\n\n"

            report_msg += "【目前持倉與權重異動】\n"
            if tg_holdings_sorted: report_msg += "\n".join(tg_holdings_sorted) + "\n"
            else: report_msg += "目前無持倉\n"

            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": report_msg, "parse_mode": "HTML"})
            print("Telegram 結算報告已成功推播")
    except Exception as e: print(f"推播失敗: {e}")

execute_pipeline()