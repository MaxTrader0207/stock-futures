"""
個股期貨動能排行 - 資料抓取腳本
資料來源：臺灣期貨交易所 OpenAPI /DailyMarketReportFut
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
}

def get_name_stock(code):
    val = NAME_MAP.get(code, "")
    if ":" in val:
        name, sid = val.split(":", 1)
        return name, sid
    return code + "期貨", ""

def fetch_daily_report():
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
        "Accept": "application/json",
    }, timeout=30)
    r.raise_for_status()
    return r.json()

def process(raw):
    # 印出前幾筆的欄位，方便 debug
    if raw:
        print(f"  欄位名稱: {list(raw[0].keys())}")
        print(f"  第一筆範例: {raw[0]}")
        sessions = set(d.get('TradingSession','') for d in raw[:100])
        print(f"  TradingSession 值: {sessions}")

    # 每個商品代碼只取近月（成交量最大或合約月份最小）
    # 不篩 TradingSession，直接取所有資料
    by_code = defaultdict(list)
    for row in raw:
        code = (row.get("ProductCode") or row.get("商品代號") or "").strip()
        if not code:
            continue
        by_code[code].append(row)

    results = []
    for code, rows in by_code.items():
        # 優先取成交量最大的那筆（近月通常成交量最大）
        def get_vol(r):
            v = str(r.get("Volume") or r.get("成交量") or "0").replace(",","")
            try: return int(v)
            except: return 0

        rows.sort(key=get_vol, reverse=True)
        row = rows[0]

        def fnum(keys, default=0):
            for k in keys:
                v = str(row.get(k) or "").replace(",","").replace("%","").strip()
                if v and v not in ("-","–",""):
                    try: return float(v)
                    except: pass
            return default

        close  = fnum(["Close","收盤價","SettlementPrice","結算價"])
        change_rate = fnum(["%Change","漲跌%","ChangePercent"])
        volume = int(fnum(["Volume","成交量"]))
        oi     = int(fnum(["OpenInterest","未沖銷契約數","未平倉量"]))

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
        print("  ⚠ 無有效資料")
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
