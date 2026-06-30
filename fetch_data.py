"""
個股期貨動能排行 - 資料抓取腳本
資料來源：
  - 行情：臺灣期貨交易所 OpenAPI /DailyMarketReportFut
  - 名稱對照：臺灣期貨交易所官方開放資料 SSFLists（股票期貨交易標的）
"""
import requests, json, sys, csv, io
from datetime import datetime, timezone, timedelta
from collections import defaultdict

TW = timezone(timedelta(hours=8))

# 備用名稱對照表（官方來源也抓不到時的最後防線）
FALLBACK_NAME_MAP = {
    "CAF":"南亞期貨:1303","CCF":"聯電期貨:2303","QZF":"力積電期貨:6770",
    "FZF":"華邦電期貨:2344","DHF":"鴻海期貨:2317","DQF":"群創期貨:3481",
    "CDF":"台積電期貨:2330","DVF":"聯發科期貨:2454",
}

def fetch_name_map():
    """從臺灣期貨交易所官方開放資料抓取股票期貨標的對照表"""
    url = "https://www.taifex.com.tw/data_gov/taifex_open_data.asp?data_name=SSFLists"
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
        }, timeout=20)
        r.raise_for_status()

        # 嘗試判斷編碼（官方CSV常見 Big5 或 UTF-8）
        raw = r.content
        text = None
        for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            print("  ⚠ 官方CSV編碼解析失敗，改用備用表")
            return {}

        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return {}

        header = rows[0]
        print(f"  官方CSV欄位: {header}")

        name_map = {}
        for row in rows[1:]:
            if len(row) < 4:
                continue
            # 欄位順序：股票期貨商品代碼, 標的證券, 證券代號, 標的證券簡稱, 標的證券種類
            code = row[0].strip()
            stock_id = row[2].strip()
            short_name = row[3].strip()
            if code and short_name:
                # 商品代碼可能是完整代碼或含括號的格式，統一處理
                clean_code = code.replace("(","").replace(")","").strip()
                name_map[clean_code] = f"{short_name}期貨:{stock_id}"

        print(f"  官方名稱對照表：載入 {len(name_map)} 筆")
        return name_map

    except Exception as e:
        print(f"  官方CSV抓取失敗（{e}），改用備用表")
        return {}

def get_name_stock(code, name_map):
    val = name_map.get(code) or FALLBACK_NAME_MAP.get(code, "")
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
    r = requests.get(
        "https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
        headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def process(raw, name_map):
    regular = [r for r in raw if r.get("TradingSession","").strip() == "一般"]
    print(f"  一般時段筆數: {len(regular)}")

    by_code = defaultdict(list)
    for row in regular:
        code = row.get("Contract","").strip()
        if code:
            by_code[code].append(row)

    results = []
    unmatched = []
    for code, rows in by_code.items():
        rows.sort(key=lambda r: to_int(r.get("Volume",0)), reverse=True)
        row = rows[0]

        close       = to_float(row.get("Last") or row.get("SettlementPrice", 0))
        change_rate = to_float(row.get("%", 0))
        volume      = to_int(row.get("Volume", 0))
        oi          = to_int(row.get("OpenInterest", 0))

        if volume == 0:
            continue

        name, stock_id = get_name_stock(code, name_map)
        if name == code + "期貨":
            unmatched.append(code)

        results.append({
            "contract":     code,
            "name":         name,
            "stockId":      stock_id,
            "close":        close,
            "changeRate":   round(change_rate, 2),
            "volume":       volume,
            "openInterest": oi,
        })

    if unmatched:
        print(f"  ⚠ 未對照到名稱的合約代碼（{len(unmatched)}個）: {unmatched[:20]}")

    return results

def main():
    now = datetime.now(TW)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 開始抓取個股期貨資料...")

    name_map = fetch_name_map()
    if not name_map:
        name_map = FALLBACK_NAME_MAP

    try:
        raw = fetch_daily_report()
        print(f"  原始資料筆數: {len(raw)}")
    except Exception as e:
        print(f"  ❌ 抓取失敗: {e}")
        sys.exit(1)

    data = process(raw, name_map)
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
