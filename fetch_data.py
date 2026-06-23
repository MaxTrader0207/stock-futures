"""
個股期貨動能排行 - 資料抓取腳本
資料來源：臺灣期貨交易所 OpenAPI
每日收盤後執行，產生 data.json 供 GitHub Pages 讀取
"""
import requests, json, sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

TW = timezone(timedelta(hours=8))

# ── 中文名稱對照表（contract code → 名稱 + 股票代號）──────────────────────
# 從 Wantgoo all-stock-futures-list 整理，之後可持續補充
NAME_MAP = {
    "CAF":"南亞期貨:1303","CCF":"聯電期貨:2303","QZF":"力積電期貨:6770",
    "FZF":"華邦電期貨:2344","DHF":"鴻海期貨:2317","DQF":"群創期貨:3481",
    "CDF":"台積電期貨:2330","YOF":"國巨期貨:2327","BAF":"台塑期貨:1301",
    "BBF":"南亞塑膠期貨:1303","BCF":"台化期貨:1326","AEF":"華新科期貨:2492",
    "AFF":"台達電期貨:2308","AGF":"日月光期貨:3711","AHF":"聯發科期貨:2454",
    "CJF":"友達期貨:2409","CKF":"彩晶期貨:6116","CLF":"台玻期貨:1802",
    "CMF":"旺宏期貨:2337","CNF":"力成期貨:6239","COF":"南電期貨:8046",
    "CPF":"合晶期貨:6182","DAF":"台積電小型期貨:2330","DBF":"聯電小型期貨:2303",
    "DCF":"鴻海小型期貨:2317","DDF":"國巨小型期貨:2327","DEF":"台達電小型期貨:2308",
    "DFF":"聯發科小型期貨:2454","DGF":"日月光小型期貨:3711","QFF":"玉晶光小型期貨:3406",
    "QWF":"穩懋小型期貨:3105","QCF":"群聯小型期貨:8299","RFF":"元大台灣50小型期貨:0050",
    "RAF":"台指期:TX","RBF":"電子期:TE","RCF":"金融期:TF",
}

def get_name_stock(code):
    """根據 contract code 回傳 (中文名稱, 股票代號)"""
    val = NAME_MAP.get(code, "")
    if ":" in val:
        name, sid = val.split(":", 1)
        return name, sid
    return code + "期貨", ""

def fetch_daily_report():
    """抓取 TAIFEX 期貨每日交易行情"""
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def process(raw):
    """
    TAIFEX DailyMarketReportFut 欄位：
    ContractDate, ContractMonth/Week, TradingSession,
    Open, High, Low, Close, Change, %Change,
    Volume, SettlementPrice, OpenInterest, BestBid, BestAsk, HistoricalHigh, HistoricalLow
    ProductCode = 商品代碼（如 CAF, CCF, ...）
    """
    # 只取近月（最小到期月份），且只取一般交易時段
    by_code = defaultdict(list)
    for row in raw:
        code = row.get("ProductCode", "").strip()
        session = row.get("TradingSession", "").strip()
        if not code or session != "一般":
            continue
        by_code[code].append(row)

    results = []
    for code, rows in by_code.items():
        # 取近月（合約月份最小的那筆）
        rows.sort(key=lambda x: x.get("ContractMonth/Week", ""))
        row = rows[0]

        try:
            close = float(str(row.get("Close", "0")).replace(",", "") or 0)
            change_rate = float(str(row.get("%Change", "0")).replace(",", "").replace("%", "") or 0)
            volume = int(str(row.get("Volume", "0")).replace(",", "") or 0)
            oi = int(str(row.get("OpenInterest", "0")).replace(",", "") or 0)
        except (ValueError, TypeError):
            continue

        if volume == 0:
            continue

        name, stock_id = get_name_stock(code)
        results.append({
            "contract": code,
            "name": name,
            "stockId": stock_id,
            "close": close,
            "changeRate": round(change_rate, 2),
            "volume": volume,
            "openInterest": oi,
        })

    return results

def main():
    now = datetime.now(TW)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 開始抓取 TAIFEX 個股期貨資料...")

    try:
        raw = fetch_daily_report()
        print(f"  原始資料筆數: {len(raw)}")
    except Exception as e:
        print(f"  ❌ 抓取失敗: {e}")
        sys.exit(1)

    data = process(raw)
    print(f"  處理後筆數: {len(data)}")

    if not data:
        print("  ⚠ 無有效資料，可能尚未收盤或非交易日")
        sys.exit(0)

    output = {
        "updateTime": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "count": len(data),
        "data": data,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ data.json 已產生（{len(data)} 筆）")

if __name__ == "__main__":
    main()
