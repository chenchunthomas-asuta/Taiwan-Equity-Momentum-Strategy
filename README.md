# 台灣股市截面動能策略：結合波動度倒數與流動性限制之實證研究
# Cross-Sectional Momentum Strategy with Inverse-Volatility Sizing and Liquidity Constraints in the Taiwan Equity Market

---

## 執行摘要 (Executive Summary)

### 中文
本專案開發並驗證了一套針對台灣上市櫃全市場（1,900+ 檔標的）的中低頻量化交易系統（V7.9.4 版本）。策略核心基於截面動能效應（Cross-Sectional Momentum），針對新台幣 1 億元之大資金規模，實作了嚴格的機構級選股濾網。透過導入「流動性天花板 (Liquidity Cap)」與「波動度倒數權重 (Inverse Volatility Sizing)」，成功平滑了動能因子帶來的極端波動。在還原除權息的完整十年牛熊轉換週期回測中，模型最終錄得 **875.02% 的累積總報酬率**，年化報酬率 (CAGR) 為 **23.87%**，夏普比率 (Sharpe Ratio) 達到 **1.01**，展現出高度的實戰交易可行性與穩健的超額報酬（Alpha）。

### English
This project implements and validates an institutional-grade, low-to-medium frequency quantitative trading system (Version 7.9.4) tailored for the Taiwan stock market (covering 1,900+ listed tickers). Built upon the cross-sectional momentum effect, the strategy enforces rigorous universe filtering optimized for a substantial capital size of 100M TWD. By incorporating **Inverse-Volatility Sizing** and an **ADV20 Liquidity Cap**, the system successfully mitigates the inherent tail risks of momentum chasers. Backtested over a comprehensive 10-year market cycle using split-adjusted prices, the model achieved a **cumulative return of 875.02%**, a **CAGR of 23.87%**, and a **Sharpe Ratio of 1.01**, proving its exceptional robustness and live-trading viability.

---

## 核心績效指標 (Key Performance Metrics)

| 績效指標 (Metrics) | V7.9.4 動態權重策略 (V7.9.4 Strategy) | 台灣50大盤基準 (0050.TW Benchmark) |
| :--- | :---: | :---: |
| **累積總報酬率 (Cumulative Return)** | **875.02%** | 大盤同期表現 (Benchmark) |
| **年化報酬率 (CAGR)** | **23.87%** | 大盤同期表現 (Benchmark) |
| **夏普比率 (Sharpe Ratio)** | **1.01** | 大盤同期表現 (Benchmark) |
| **最大回撤 (Max Drawdown)** | **-47.67%** | 大盤同期表現 (Benchmark) |
| **年化雙邊換手率 (Annualized Turnover)** | **285.11%** | -- |
| **平均單日換手率 (Avg Daily Turnover)** | **1.13%** | -- |

---

## 策略架構與因子工程 (Strategy Architecture & Factor Engineering)

### 1. 雙階選股濾網 (Two-Stage Universe Filtering)
* **大盤總經濾網 (Market Filter):** 標的指數 (0050.TW) 必須高於其 60日均線 (SMA60)，否則系統判定為系統性熊市，強制清倉轉入現金防禦，從根本上避開如 2022 年的系統性主跌段。
* **個股趨勢保護 (Individual Trend Filter):** 個股價格必須高於其 20日均線 (SMA20)，確保不參與左側交易。
* **法人流動性門檻 (Liquidity Threshold):** 過去 20 日平均成交金額 (`ADV_20`) 必須 **> 5,000萬新台幣**，且股價高於 10 元，徹底剔除缺乏流動性且易受操縱的殭屍股與水餃股。

### 2. 風險平價部位分配 (Risk Parity & Sizing Logic)
系統每日對通過濾網的股票計算 120日累積報酬率 (`Mom_120`) 並進行橫截面降序排列，挑選**前 20 名**強勢股建倉。權重分配融合了三大法人級風控機制：
* **階梯乘數 (Rank Multiplier):** 資源集中於黃金動能圈（第 1-5 名乘數 1.5；6-10 名乘數 1.0；11-20 名乘數 0.5）。
* **波動度倒數 (Inverse Volatility):** 權重公式為 `Raw_Weight = (1 / Vol_20) * Rank_Multiplier`。強制降低高波動飆股的曝險，補貼走勢平穩的標的，藉此平滑淨值曲線並拉高夏普率。
* **流動性天花板 (Liquidity Cap):** 單一標的單日下單金額嚴格限制在該股 `ADV_20` 的 **10%** 以內，且單檔權重上限為 **20%**，將大資金在實盤開盤時的市場衝擊成本（Market Impact）與惡性滑價控制在預期之內。

---

## 檔案結構 (Repository Structure)

* `main.py`
  * **中文:** 實盤自動化交易與推播引擎。串接富果 Fugle API 獲取即時/盤後市場微結構特徵，內建狀態機執行一階警報（破5MA減碼50%）與二階死線風控，並透過 Telegram Bot 推播每日調倉報告。
  * **English:** Live-trading execution engine integrated with Fugle API. Built-in state machine handles risk management (50% reduction upon breaching SMA5, 100% exit on SMA20/Rank breakdown) and dispatches automated rebalancing reports via Telegram Bot.
* `v7_full_backtest.py`
  * **中文:** 全市場向量化歷史回測框架（2015-2025）。使用還原收盤價（Adj Close）精確對齊多維矩陣（`df_rets_aligned`），完美模擬月底再平衡、複利滾存與交易摩擦摩擦成本，杜絕前瞻偏誤（Look-ahead Bias）。
  * **English:** Vectorized backtesting framework covering 1,900+ tickers (2015-2025). Utilizes split-adjusted prices and perfectly aligns multi-dimensional dataframes (`df_rets_aligned`) to simulate monthly rebalancing and friction costs without Look-ahead Bias.
* `Quantitative_Research_Whitepaper.pdf`
  * **中文:** 完整的量化研究報告。內含詳細的計量哲學、2022年回撤深度解剖、2021年典型持倉案例（2609陽明波段獲利249.92%之微結構剖析）以及參數敏感度強健性測試。
  * **English:** Full-length quantitative research whitepaper, detailing factor robust test, 2022 drawdown autopsy, and a micro-structure case study on 2609.TW (capturing a 249.92% trend ride).

---

## 快速開始 (Getting Started)

### Prerequisites
```bash
pip install yfinance pandas numpy matplotlib requests tqdm fugle-marketdata
