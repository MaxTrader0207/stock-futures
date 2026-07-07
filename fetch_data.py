"""
個股期貨動能排行 - 資料抓取腳本
資料來源：
  - 期貨行情：臺灣期貨交易所 OpenAPI /DailyMarketReportFut
  - 名稱對照：臺灣期貨交易所官方開放資料 SSFLists（股票期貨交易標的）

擴充欄位（皆由期貨自身歷史資料計算，零外部依賴）：
  - 開高低、振幅：取自當日行情欄位
  - OI增減：與前一交易日未平倉量比較（history.json 累積）
  - 月均量：近20個交易日成交量平均（history.json 累積）
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
    # 指數期貨（非個股期貨，但顯示更友善的中文名稱）
    "TX":"台指期貨:","MTX":"小型台指期貨:","TMF":"微型台指期貨:","M1F":"台灣中型100期貨:",
    "TE":"電子期貨:","ZEF":"小型電子期貨:","SOF":"半導體30期貨:","TF":"金融期貨:",
    "ZFF":"小型金融期貨:","XIF":"非金電期貨:","TJF":"東證期貨:","GTF":"櫃買期貨:",
    "G2F":"富櫃200期貨:","E4F":"永續期貨:","BTF":"生技期貨:","SHF":"航運期貨:",
    "GDF":"黃金期貨:","F1F":"富時台灣期貨:","FT1":"富時台灣期貨:","BRF":"布蘭特原油期貨:",
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
    except (ValueError, AttributeError):
        return default

def to_int(s, default=0):
    try:
        return int(str(s).replace(",","").strip())
    except:
        return default

HISTORY_FILE = "history.json"
HISTORY_KEEP_DAYS = 25  # 保留略多於20天，確保月均量可計算

def load_history():
    """讀取期貨自身歷史記錄 {contract: {date: {oi, volume}}}"""
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 防呆：偵測是否為舊版格式（value 直接是數字，而非 {oi, volume} 物件）
        for code, records in list(data.items())[:1]:
            for date, val in records.items():
                if not isinstance(val, dict):
                    print("  ⚠ 偵測到舊版 history.json 格式，重新建立")
                    return {}
                break
            break
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)

def update_history(history, date_str, data):
    """把今日 OI、成交量寫入歷史，並裁切只保留最近 HISTORY_KEEP_DAYS 天"""
    for item in data:
        code = item["contract"]
        if code not in history:
            history[code] = {}
        history[code][date_str] = {
            "oi":     item["openInterest"],
            "volume": item["volume"],
        }

    for code in history:
        dates_sorted = sorted(history[code].keys(), reverse=True)
        keep = dates_sorted[:HISTORY_KEEP_DAYS]
        history[code] = {d: history[code][d] for d in keep}

    return history

def calc_oi_change(history, code, today_str, current_oi):
    """
    計算未平倉量較前一交易日的增減（口數）
    歷史不足（無前一日資料）時回傳 None
    """
    records = history.get(code, {})
    other_dates = sorted([d for d in records if d != today_str], reverse=True)
    if not other_dates:
        return None
    prev_oi = records[other_dates[0]].get("oi")
    if prev_oi is None:
        return None
    return current_oi - prev_oi

def calc_monthly_avg_volume(history, code, today_str, current_volume):
    """
    計算近20個交易日（含今日）的平均成交量
    可用天數不足時，以實際可用天數計算（至少需2天才有意義）
    """
    records = dict(history.get(code, {}))
    records[today_str] = {"oi": None, "volume": current_volume}  # 確保今日算入
    dates_sorted = sorted(records.keys(), reverse=True)
    last_n = dates_sorted[:20]
    volumes = [records[d]["volume"] for d in last_n if records[d].get("volume") is not None]
    if len(volumes) < 2:
        return None
    return round(sum(volumes) / len(volumes))

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
        # 取最近月：合約月份最小的那筆（ContractMonth/Week 格式為 YYYYMM 或 YYYYMMW）
        rows.sort(key=lambda r: r.get("ContractMonth/Week", "9999"))
        row = rows[0]

        # 確保近月合約有成交，否則取成交量最大的
        if to_int(row.get("Volume", 0)) == 0:
            rows_with_vol = [r for r in rows if to_int(r.get("Volume", 0)) > 0]
            if not rows_with_vol:
                continue
            row = rows_with_vol[0]

        close       = to_float(row.get("Last") or row.get("SettlementPrice", 0))
        open_price  = to_float(row.get("Open", 0))
        high_price  = to_float(row.get("High", 0))
        low_price   = to_float(row.get("Low", 0))
        change      = to_float(row.get("Change", 0))
        change_rate = to_float(row.get("%", 0))
        volume      = to_int(row.get("Volume", 0))
        oi          = to_int(row.get("OpenInterest", 0))

        # 振幅 = (最高-最低) / 前一日收盤(=今收-漲跌) × 100%
        prev_close = close - change
        amplitude = None
        if prev_close > 0 and high_price and low_price:
            amplitude = round((high_price - low_price) / prev_close * 100, 2)

        name, stock_id = get_name_stock(code, name_map)
        if name == code + "期貨":
            unmatched.append(code)

        results.append({
            "contract":     code,
            "name":         name,
            "stockId":      stock_id,
            "close":        close,
            "open":         open_price,
            "high":         high_price,
            "low":          low_price,
            "change":       round(change, 2),
            "changeRate":   round(change_rate, 2),
            "amplitude":    amplitude,
            "volume":       volume,
            "openInterest": oi,
        })

    # 指數期貨（非個股期貨）不需要名稱對照，過濾掉避免誤判
    INDEX_FUTURES = {
        "TX","MTX","TMF","M1F","TE","ZEF","SOF","TF","ZFF","XIF","TJF",
        "XJF","XEF","XBF","UNF","UDF","TGF","SXF","RHF","QO1",
        "GTF","G2F","E4F","BTF","SHF","NQF","GDF","F1F","FT1","BRF",
    }
    real_unmatched = [c for c in unmatched if c not in INDEX_FUTURES]
    if real_unmatched:
        print(f"  ⚠ 未對照到名稱的合約代碼（{len(real_unmatched)}個，已排除指數期貨）: {real_unmatched}")
    else:
        print(f"  ✅ 所有個股期貨皆已對照成功（已排除 {len(unmatched)} 檔指數期貨）")

    return results

def main():
    now = datetime.now(TW)
    today_str = now.strftime("%Y-%m-%d")
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

    # ── OI增減 / 月均量計算（皆來自期貨自身歷史，零外部依賴） ──────────
    history = load_history()

    oi_ready_count = 0
    vol_ready_count = 0
    for item in data:
        code = item["contract"]

        oi_change = calc_oi_change(history, code, today_str, item["openInterest"])
        item["oiChange"] = oi_change
        if oi_change is not None:
            oi_ready_count += 1

        monthly_avg_vol = calc_monthly_avg_volume(history, code, today_str, item["volume"])
        item["monthlyAvgVolume"] = monthly_avg_vol
        if monthly_avg_vol is not None:
            vol_ready_count += 1

    history = update_history(history, today_str, data)
    save_history(history)

    print(f"  OI增減：{oi_ready_count}/{len(data)} 檔已可計算（首次執行無前一日資料屬正常）")
    print(f"  月均量：{vol_ready_count}/{len(data)} 檔已可計算（隨天數增加會更準確，最多採近20交易日）")

    output = {
        "updateTime": now.strftime("%Y-%m-%d %H:%M"),
        "date":       today_str,
        "count":      len(data),
        "data":       data,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ data.json 已產生（{len(data)} 筆）")

if __name__ == "__main__":
    main()
