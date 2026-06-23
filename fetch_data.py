"""
個股期貨動能排行 - 資料抓取腳本
資料來源：臺灣期貨交易所 OpenAPI /DailyMarketReportFut
欄位：Date, Contract, ContractMonth(Week), Open, High, Low, Last,
      Change, %, Volume, SettlementPrice, OpenInterest,
      BestBid, BestAsk, HistoricalHigh, HistoricalLow,
      TradingHalt, TradingSession
"""
import requests, json, sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

TW = timezone(timedelta(hours=8))

NAME_MAP = {
    "CAF":"南亞期貨:1303","CCF":"聯電期貨:2303","QZF":"力積電期貨:6770",
    "FZF":"華邦電期貨:2344","DHF":"鴻海期貨:2317","DQF":"群創期貨:3481",
    "CDF":"台積電期貨:2330","YOF":"國巨期貨:2327","BAF":"台塑期貨:1301",
    "AEF":"華新科期貨:2492","AFF":"台達電期貨:2308","AGF":"日月光期貨:3711",
    "AHF":"聯發科期貨:2454","CJF":"友達期貨:2409","CKF":"彩晶期貨:6116",
    "CLF":"台玻期貨:1802","CMF":"旺宏期貨:2337","CNF":"力成期貨:6239",
    "COF":"南電期貨:8046","CPF":"合晶期貨:6182",
    "DAF":"小型台積電期貨:2330","DBF":"小型聯電期貨:2303",
    "DCF":"小型鴻海期貨:2317","DDF":"小型國巨期貨:2327",
    "DEF":"小型台達電期貨:2308","DFF":"小型聯發科期貨:2454",
    "DGF":"小型日月光期貨:3711","QFF":"小型玉晶光期貨:3406",
    "QWF":"小型穩懋期貨:3105","QCF":"小型群聯期貨:8299",
    "RFF":"小型元大台灣50期貨:0050","YDF":"小型南電期貨:8046",
    "ZFF":"華邦電期貨:2344","BEF":"南亞科期貨:2408",
}

def get_name_stock(code):
    val = NAME_MAP.get(code, "")
    if ":" in val:
        name, sid = val.split(":", 1)
        return name, sid
    return code + "期貨", ""

def to_float(s, default=0.0):
    try:
        return float(str(s).replace(",","").replace("%","").strip())
    except:
        return default

def to_int(s, default=0):
    try:
        return int(str(s).replace(",","").strip())
    except:
        return default

def fetch_daily_report():
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
        "Accept": "application/json",
    }, timeout=30)
    r.raise_for_status()
    return r.json()

def process(raw):
    # 只取一般交易時段
    regular = [r for r in raw if r.get("TradingSession","").strip() == "一般"]
    print(f"  一般時段筆數: {len(regular)}")

    # 每個合約代碼取成交量最大的那筆（近月）
    by_code = defaultdict(list)
    for row in regular:
        code = row.get("Contract","").strip()
        if code:
            by_code[code].append(row)

    results = []
    for code, rows in by_code.items():
        # 取成交量最大（近月）
        rows.sort(key=lambda r: to_int(r.get("Volume",0)), reverse=True)
        row = rows[0]

        close       = to_float(row.get("Last") or row.get("SettlementPrice", 0))
        change_rate = to_float(row.get("%", 0))   # 欄位名稱就是 "%"
        volume      = to_int(row.get("Volume", 0))
        oi          = to_int(row.get("OpenInterest", 0))

        if volume == 0:
            continue

        name, stock_id = get_name_stock(code)
        results.append({
            "contract":    code,
            "name":        name,
            "stockId":     stock_id,
            "close":       close,
            "changeRate":  round(change_rate, 2),
            "volume":      volume,
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
        "date":       now.strftime("%Y-%m-%d"),
        "count":      len(data),
        "data":       data,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ data.json 已產生（{len(data)} 筆）")

if __name__ == "__main__":
    main()
