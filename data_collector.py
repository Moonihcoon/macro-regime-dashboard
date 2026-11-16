"""
1단계: 데이터 수집기
- FRED(미국 금리·달러·신용·VIX·유가), Yahoo Finance(반도체지수·구리·S&P500),
  KRX(KODEX 200, 코스피200, 외국인 순매수), 한국은행 ECOS(CD금리·기준금리·국고채)
- 각 원천을 data/raw/*.csv 로 저장한 뒤, 한국 영업일 달력에 맞춰
  '그날 아침 한국장에서 실제로 알 수 있었던 값'으로 정렬해 data/merged_daily.csv 생성

사용법:
    pip install pandas numpy requests pykrx yfinance matplotlib
    python data_collector.py --start 2005-01-01 --ecos-key 발급받은키
    (ECOS 키는 https://ecos.bok.or.kr/api/ 에서 무료 발급, 없으면 생략 가능)

매일 장 시작 전(예: 07:30) 스케줄러로 실행하면 자동 갱신됩니다.
"""
import argparse
import io
import os
import shutil
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import config as C

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
ECOS_URL = ("https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/"
            "{stat}/{cycle}/{start}/{end}/{item}")


def _retry(fn, tries=3, wait=2.0):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # 네트워크 일시 오류 대비
            if i == tries - 1:
                raise
            print(f"  재시도 {i + 1}/{tries - 1}: {e}")
            time.sleep(wait * (i + 1))


# ---------------------------------------------------------------------------
# 원천별 수집 함수
# ---------------------------------------------------------------------------
def fetch_fred(start: str) -> pd.DataFrame:
    frames = {}
    for name, spec in C.FRED_SERIES.items():
        print(f"[FRED] {spec['id']:<14} {spec['desc']}")
        def get():
            r = requests.get(FRED_URL.format(sid=spec["id"], start=start), timeout=30)
            r.raise_for_status()
            return r.text
        df = pd.read_csv(io.StringIO(_retry(get)))
        df.columns = ["date", name]
        df["date"] = pd.to_datetime(df["date"])
        s = pd.to_numeric(df[name], errors="coerce")   # FRED 결측치 '.' 처리
        frames[name] = pd.Series(s.values, index=df["date"], name=name)
    return pd.concat(frames.values(), axis=1)


def ensure_ascii_ca_bundle():
    """사용자 폴더명에 한글이 있으면 curl 기반 라이브러리(yfinance)가 인증서 파일을 못 읽는다.
    그런 경우 ASCII 경로로 인증서를 복사해 환경변수로 알려준다."""
    try:
        import certifi
        src = Path(certifi.where())
        str(src).encode("ascii")
        return
    except UnicodeEncodeError:
        pass
    except Exception:
        return
    dst_dir = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "macro_quant_ca"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "cacert.pem"
    shutil.copyfile(src, dst)
    for v in ("CURL_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        os.environ[v] = str(dst)
    print(f"[SSL] 인증서를 ASCII 경로로 복사: {dst}")


def yf_close(ticker: str, start: str):
    """Yahoo 종가 시리즈 반환. 실패하면 None (예외를 던지지 않음)"""
    import yfinance as yf
    try:
        df = _retry(lambda: yf.download(ticker, start=start, progress=False,
                                        auto_adjust=True))
    except Exception as e:
        print(f"  ! {ticker} 다운로드 실패: {e}")
        return None
    if df is None or df.empty or "Close" not in df:
        print(f"  ! {ticker} 데이터 없음")
        return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):      # yfinance 버전에 따라 MultiIndex
        close = close.iloc[:, 0]
    close = close.dropna()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


def fetch_yahoo(start: str) -> pd.DataFrame:
    frames = {}
    for name, spec in C.YF_SERIES.items():
        print(f"[Yahoo] {spec['ticker']:<8} {spec['desc']}")
        s = yf_close(spec["ticker"], start)
        if s is not None:
            frames[name] = s.rename(name)
    return pd.concat(frames.values(), axis=1) if frames else pd.DataFrame()


def fetch_korea_yahoo(start: str) -> pd.DataFrame:
    """KRX 로그인 없이 Yahoo Finance에서 KODEX 200과 코스피200 지수를 받는다 (외국인 순매수는 제외)"""
    frames = {}
    for name, ticker in [("kodex200", "069500.KS"), ("kospi200", "^KS200")]:
        print(f"[Yahoo-KR] {ticker}")
        s = yf_close(ticker, start)
        if s is not None:
            frames[name] = s.rename(name)
    if "kodex200" not in frames and "kospi200" not in frames:
        raise RuntimeError("KODEX 200과 코스피200 지수를 모두 받지 못했습니다. 인터넷 연결과 위쪽 오류 메시지를 확인하세요.")
    out = pd.concat(frames.values(), axis=1)
    # Yahoo의 ^KS200은 이력이 하루치만 오는 경우가 있다 → 이력이 짧으면 KODEX 200 가격으로 대체
    if "kodex200" in out and ("kospi200" not in out or out["kospi200"].notna().sum() < 200):
        print("! 코스피200 지수 이력이 부족 → KODEX 200 가격만 사용합니다 (2007년~)")
        out["kospi200"] = out["kodex200"]
    elif "kodex200" not in out:
        out["kodex200"] = np.nan
    return out


def fetch_krx(start: str, end: str) -> pd.DataFrame:
    from pykrx import stock
    s, e = start.replace("-", ""), end.replace("-", "")

    print(f"[KRX] KODEX 200 ({C.KRX_ETF_TICKER})")
    etf = _retry(lambda: stock.get_etf_ohlcv_by_date(s, e, C.KRX_ETF_TICKER))
    etf_close = etf["종가"].rename("kodex200")

    print(f"[KRX] 코스피200 지수 ({C.KRX_INDEX_CODE})")
    idx = _retry(lambda: stock.get_index_ohlcv_by_date(s, e, C.KRX_INDEX_CODE))
    idx_close = idx["종가"].rename("kospi200")

    # 외국인 순매수 (코스피 전체, 원) - 기간이 길면 연 단위로 나눠 요청
    print("[KRX] 코스피 투자자별 순매수 (외국인)")
    parts = []
    for y in range(int(s[:4]), int(e[:4]) + 1):
        ys, ye = max(s, f"{y}0101"), min(e, f"{y}1231")
        df = _retry(lambda: stock.get_market_trading_value_by_date(ys, ye, "KOSPI"))
        parts.append(df)
        time.sleep(0.5)                           # KRX 서버 부하 방지
    flow = pd.concat(parts)
    col = [c for c in flow.columns if "외국인" in c][0]
    foreign = flow[col].rename("foreign_net")

    out = pd.concat([etf_close, idx_close, foreign], axis=1)
    out.index = pd.to_datetime(out.index)
    return out


def fetch_ecos(key: str, start: str, end: str) -> pd.DataFrame:
    frames = {}
    for name, spec in C.ECOS_SERIES.items():
        print(f"[ECOS] {spec['stat']}/{spec['item']} {spec['desc']}")
        url = ECOS_URL.format(key=key, stat=spec["stat"], cycle=spec["cycle"],
                              start=start.replace("-", ""), end=end.replace("-", ""),
                              item=spec["item"])
        def get():
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.json()
        js = _retry(get)
        rows = js.get("StatisticSearch", {}).get("row", [])
        if not rows:
            print(f"  ! 데이터 없음: {js.get('RESULT', js)}")
            continue
        df = pd.DataFrame(rows)
        s = pd.Series(pd.to_numeric(df["DATA_VALUE"], errors="coerce").values,
                      index=pd.to_datetime(df["TIME"], format="%Y%m%d"), name=name)
        frames[name] = s
    return pd.concat(frames.values(), axis=1) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Point-in-time 정렬: 이 부분이 백테스트 신뢰도를 좌우합니다
# ---------------------------------------------------------------------------
def align_point_in_time(krx: pd.DataFrame, foreign_frames: dict) -> pd.DataFrame:
    """
    krx: 한국 영업일 인덱스를 가진 국내 데이터 (달력 기준)
    foreign_frames: {원천이름: (DataFrame, {컬럼: lag_days})}

    방식: 해외 데이터는 '자기 나라 영업일' 기준으로 lag만큼 뒤로 밀어(shift)
          가용 시점을 만든 뒤, 한국 영업일에 asof(직전 가용값)로 붙인다.
          → 한국장 t일에는 t일 이전에 확정·공표된 값만 보이게 됨
    """
    cal = krx.index.sort_values()
    merged = krx.copy()
    for src, (df, lags) in foreign_frames.items():
        if df is None or df.empty:
            continue
        df = df.sort_index()
        for col, lag in lags.items():
            if col not in df.columns:
                continue
            s = df[col].dropna()
            # 가용 시점 = 관측일 + lag 영업일(미국 기준 근사: 평일)
            avail = s.copy()
            avail.index = avail.index + pd.offsets.BDay(lag)
            # 같은 한국 영업일에 여러 값이 몰리면 마지막 값
            avail = avail[~avail.index.duplicated(keep="last")]
            merged[col] = avail.reindex(cal, method="ffill")
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=C.START_DATE)
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--ecos-key", default=None, help="한국은행 ECOS API 키 (선택)")
    args = ap.parse_args()

    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    ensure_ascii_ca_bundle()

    fred = fetch_fred(args.start)
    fred.to_csv(C.RAW_DIR / "fred.csv")

    try:
        yahoo = fetch_yahoo(args.start)
        if not yahoo.empty:
            yahoo.to_csv(C.RAW_DIR / "yahoo.csv")
    except ImportError:
        print("! yfinance 미설치 → 반도체지수·구리 없이 진행 (pip install yfinance)")
        yahoo = pd.DataFrame()

    # 국내 데이터: KRX 계정(환경변수 KRX_ID, KRX_PW)이 있으면 pykrx, 없으면 Yahoo
    krx = None
    if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
        try:
            krx = fetch_krx(args.start, args.end)
        except Exception as e:
            print(f"! KRX(pykrx) 실패 → Yahoo로 대체: {e}")
    if krx is None:
        krx = fetch_korea_yahoo(args.start)
    krx.to_csv(C.RAW_DIR / "krx.csv")

    ecos = pd.DataFrame()
    if args.ecos_key:
        ecos = fetch_ecos(args.ecos_key, args.start, args.end)
        ecos.to_csv(C.RAW_DIR / "ecos.csv")

    # 국내 데이터: 한국 영업일 달력의 기준
    krx = krx.dropna(subset=["kospi200"])
    # ETF 상장 전 구간은 코스피200 지수 수익률로 보완한 '거래 가능 가격' 시리즈
    krx["tradable"] = splice_price(
        krx.get("kodex200", pd.Series(np.nan, index=krx.index)), krx["kospi200"])

    foreign = {
        "fred":  (fred,  {k: v["lag_days"] for k, v in C.FRED_SERIES.items()}),
        "yahoo": (yahoo, {k: v["lag_days"] for k, v in C.YF_SERIES.items()}),
        # ECOS 금리는 당일 장중 확정되므로 보수적으로 1일 지연
        "ecos":  (ecos,  {k: 1 for k in C.ECOS_SERIES}),
    }
    merged = align_point_in_time(krx, foreign)
    merged.index.name = "date"
    missing = [c for c in ["us2y", "usdkrw", "hy_oas", "vix", "sox", "copper"]
               if c not in merged or merged[c].isna().all()]
    if missing:
        print(f"\n! 받지 못한 변수: {missing} → 해당 변수는 레짐 점수에서 제외됩니다")
    merged.to_csv(C.DATA_FILE)
    print(f"\n저장 완료: {C.DATA_FILE}  ({len(merged):,}행, "
          f"{merged.index.min().date()} ~ {merged.index.max().date()})")
    print(merged.tail(3).T)


def splice_price(etf: pd.Series, index: pd.Series) -> pd.Series:
    """ETF 가격이 없는 과거 구간을 지수 수익률로 거꾸로 이어 붙임"""
    etf = etf.astype(float)
    first = etf.first_valid_index()
    if first is None:
        return index.astype(float)
    ratio = etf.loc[first] / index.loc[first]
    out = etf.copy()
    out.loc[:first] = index.loc[:first] * ratio
    return out.ffill()


if __name__ == "__main__":
    main()
