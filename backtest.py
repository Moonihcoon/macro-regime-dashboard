"""
2단계: 레짐 기반 '코스피200 ETF ↔ 현금' 비중 조절 백테스트

실행:
    python backtest.py            # data/merged_daily.csv 사용 (data_collector.py 먼저 실행)
    python backtest.py --demo     # 가상 데이터로 동작 확인
    python backtest.py --rebalance ME --start 2010-01-01

출력 (output/ 폴더):
    summary.csv           전략 vs 매수후보유 성과 지표
    regime_report.csv     국면별 다음 1개월 수익률 통계
    score_buckets.csv     레짐 점수 5분위별 수익률 (단조성 확인)
    sensitivity.csv       파라미터 민감도 (과최적화 점검)
    yearly.csv            연도별 수익률
    daily_result.csv      일별 비중·수익률·누적자산
    backtest_chart.png    누적수익률 / 낙폭 / 주식 비중 차트
"""
import argparse
import copy
import itertools

import numpy as np
import pandas as pd

import config as C
from regime import compute_regime, regime_report, score_bucket_report

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# 시뮬레이션
# ---------------------------------------------------------------------------
def run_backtest(df: pd.DataFrame, reg: pd.DataFrame, bt: dict = None,
                 price_col: str = "tradable") -> pd.DataFrame:
    bt = bt or C.BACKTEST
    px = df[price_col].astype(float)
    r_eq = px.pct_change(fill_method=None).fillna(0.0)

    if "cd91" in df and df["cd91"].notna().any():
        cash_rate = df["cd91"].ffill().fillna(bt["default_cash_rate"])
    else:
        cash_rate = pd.Series(bt["default_cash_rate"], index=df.index)
    r_cash = cash_rate / 100 / TRADING_DAYS

    # 리밸런싱일: 해당 주기의 마지막 영업일 신호를 '다음 영업일 종가'에 체결
    target = reg["target_weight"]
    dates = df.index
    period_last = pd.Series(dates, index=dates).groupby(
        pd.Grouper(freq=bt["rebalance"])).last().dropna()
    is_signal_day = pd.Series(False, index=dates)
    is_signal_day.loc[period_last.values] = True

    w_hold = np.zeros(len(dates))       # 그날 수익률에 노출된 비중 (전일 종가 기준)
    cost = np.zeros(len(dates))
    trade = np.zeros(len(dates))
    w = 0.0
    pending = None
    tgt = target.values
    sig = is_signal_day.values
    req = r_eq.values
    one_way = bt["commission"] + bt["slippage"]

    for i in range(len(dates)):
        w_hold[i] = w
        # 보유 비중은 가격 변동으로 자연 이동
        port_r = w * req[i] + (1 - w) * r_cash.values[i]
        if 1 + port_r != 0:
            w = w * (1 + req[i]) / (1 + port_r)
        # 전일 신호를 오늘 종가에 체결
        if pending is not None and not np.isnan(pending):
            if abs(pending - w) >= bt["band"]:
                dw = pending - w
                trade[i] = abs(dw)
                cost[i] = abs(dw) * one_way + max(-dw, 0) * bt["sell_tax"]
                w = pending
            pending = None
        if sig[i]:
            pending = tgt[i]

    res = pd.DataFrame(index=dates)
    res["w_equity"] = w_hold
    res["r_equity"] = r_eq
    res["r_cash"] = r_cash
    res["cost"] = cost
    res["turnover"] = trade
    res["r_strategy"] = res["w_equity"] * res["r_equity"] + (1 - res["w_equity"]) * res["r_cash"] - res["cost"]
    res["r_buyhold"] = res["r_equity"]
    # 비교군: 60/40 고정 (주식 60% / 현금 40%, 월말 리밸런싱 근사)
    res["r_fixed60"] = 0.6 * res["r_equity"] + 0.4 * res["r_cash"]
    for k in ["strategy", "buyhold", "fixed60"]:
        res[f"nav_{k}"] = (1 + res[f"r_{k}"]).cumprod()
    return res


def metrics(r: pd.Series, r_cash: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 2:
        return {}
    nav = (1 + r).cumprod()
    years = len(r) / TRADING_DAYS
    cagr = nav.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(TRADING_DAYS)
    ex = r - r_cash.reindex(r.index).fillna(0)
    sharpe = ex.mean() / ex.std() * np.sqrt(TRADING_DAYS) if ex.std() > 0 else np.nan
    dd = nav / nav.cummax() - 1
    mdd = dd.min()
    return {
        "CAGR(%)": round(cagr * 100, 2),
        "변동성(%)": round(vol * 100, 2),
        "샤프": round(sharpe, 2),
        "MDD(%)": round(mdd * 100, 2),
        "칼마": round(cagr / abs(mdd), 2) if mdd < 0 else np.nan,
        "최종배수": round(nav.iloc[-1], 2),
    }


def summarize(res: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for k, name in [("strategy", "레짐 전략"), ("buyhold", "코스피200 보유"), ("fixed60", "고정 60/40")]:
        rows[name] = metrics(res[f"r_{k}"], res["r_cash"])
    out = pd.DataFrame(rows).T
    years = len(res) / TRADING_DAYS
    out.loc["레짐 전략", "연 회전율(배)"] = round(res["turnover"].sum() / years, 2)
    out.loc["레짐 전략", "평균 주식비중(%)"] = round(res["w_equity"].mean() * 100, 1)
    out.loc["레짐 전략", "연 비용(%)"] = round(res["cost"].sum() / years * 100, 3)
    return out


def yearly(res: pd.DataFrame) -> pd.DataFrame:
    g = res.groupby(res.index.year)
    y = pd.DataFrame({
        "레짐 전략(%)": g["r_strategy"].apply(lambda x: (1 + x).prod() - 1) * 100,
        "코스피200(%)": g["r_buyhold"].apply(lambda x: (1 + x).prod() - 1) * 100,
        "평균 주식비중(%)": g["w_equity"].mean() * 100,
    }).round(1)
    y["초과(%p)"] = (y["레짐 전략(%)"] - y["코스피200(%)"]).round(1)
    return y


# ---------------------------------------------------------------------------
# 강건성: 파라미터 민감도
#   좋은 전략은 '특정 숫자 하나'에서만 좋은 게 아니라 주변 값에서도 고르게 좋아야 함
# ---------------------------------------------------------------------------
def sensitivity(df: pd.DataFrame, start=None) -> pd.DataFrame:
    grid = {
        "mom_window": [42, 63, 126],
        "slope": [0.10, 0.15, 0.20],
        "vix_crisis": [25.0, 30.0, 35.0],
    }
    rows = []
    for mw, sl, vx in itertools.product(*grid.values()):
        p = copy.deepcopy(C.REGIME)
        p.update(mom_window=mw, slope=sl, vix_crisis=vx)
        reg = compute_regime(df, p)
        res = run_backtest(df, reg)
        if start:
            res = res.loc[start:]
        m = metrics(res["r_strategy"], res["r_cash"])
        rows.append({"mom_window": mw, "slope": sl, "vix_crisis": vx, **m})
    return pd.DataFrame(rows).sort_values("샤프", ascending=False)


# ---------------------------------------------------------------------------
# 차트
# ---------------------------------------------------------------------------
def plot(res: pd.DataFrame, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 한글 폰트 (Windows: Malgun Gothic, macOS: AppleGothic, Linux: NanumGothic)
    for f in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"]:
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1.3, 1.3]})
    ax[0].plot(res.index, res["nav_strategy"], label="Regime strategy", lw=1.6, color="#1f5fbf")
    ax[0].plot(res.index, res["nav_buyhold"], label="KOSPI200 buy & hold", lw=1.1, color="#888888")
    ax[0].plot(res.index, res["nav_fixed60"], label="Fixed 60/40", lw=1.0, color="#c98a2b", alpha=0.8)
    ax[0].set_yscale("log")
    ax[0].set_title("Cumulative growth (log)")
    ax[0].legend(loc="upper left", frameon=False)
    ax[0].grid(alpha=0.25)

    for k, c in [("strategy", "#1f5fbf"), ("buyhold", "#888888")]:
        nav = res[f"nav_{k}"]
        ax[1].fill_between(res.index, (nav / nav.cummax() - 1) * 100, 0, color=c, alpha=0.35)
    ax[1].set_title("Drawdown (%)")
    ax[1].grid(alpha=0.25)

    ax[2].fill_between(res.index, res["w_equity"] * 100, 0, color="#1f5fbf", alpha=0.5, step="post")
    ax[2].set_ylim(0, 100)
    ax[2].set_title("Equity weight (%)")
    ax[2].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="가상 데이터로 실행")
    ap.add_argument("--start", default=None, help="성과 측정 시작일 (예: 2010-01-01)")
    ap.add_argument("--rebalance", default=None, help="W-FRI 또는 ME")
    ap.add_argument("--no-sensitivity", action="store_true")
    args = ap.parse_args()

    if args.rebalance:
        C.BACKTEST["rebalance"] = args.rebalance

    if args.demo:
        from demo_data import make_demo
        df = make_demo()
        print("※ 가상 데이터 모드: 성과 수치는 의미 없음 (동작 확인용)\n")
    else:
        df = pd.read_csv(C.DATA_FILE, index_col="date", parse_dates=True)

    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    reg = compute_regime(df)
    print("레짐 점수에 사용된 변수:", reg.attrs.get("used_vars"))
    res = run_backtest(df, reg)
    # 레짐 점수가 계산되기 시작한 시점(워밍업 이후)부터 평가
    first = reg["target_weight"].first_valid_index()
    if first is None:
        raise SystemExit("레짐 점수를 계산할 데이터가 부족합니다. data/merged_daily.csv의 행 수와 "
                         "data_collector.py 출력의 '받지 못한 변수' 메시지를 확인하세요.")
    start = max(pd.Timestamp(args.start), first) if args.start else first
    res = res.loc[start:].copy()
    for k in ["strategy", "buyhold", "fixed60"]:
        res[f"nav_{k}"] = (1 + res[f"r_{k}"]).cumprod()

    summary = summarize(res)
    rep = regime_report(df.loc[start:], reg.loc[start:])
    buckets = score_bucket_report(df.loc[start:], reg.loc[start:])
    yr = yearly(res)

    pd.set_option("display.width", 160)
    pd.set_option("display.unicode.east_asian_width", True)
    print(f"평가 기간: {res.index[0].date()} ~ {res.index[-1].date()}  "
          f"/ 리밸런싱: {C.BACKTEST['rebalance']}\n")
    print("■ 성과 요약\n", summary.to_string(), "\n")
    print("■ 국면별 다음 21영업일 코스피200 수익률\n", rep.to_string())
    print("  위기 플래그 on/off 시 평균(%):", rep.attrs.get("crisis_fwd"), "\n")
    print("■ 레짐 점수 5분위별 (Q1 최저 → Q5 최고: 단조 증가하면 좋은 신호)\n", buckets.to_string(), "\n")
    print("■ 연도별\n", yr.to_string(), "\n")

    summary.to_csv(C.OUT_DIR / "summary.csv", encoding="utf-8-sig")
    rep.to_csv(C.OUT_DIR / "regime_report.csv", encoding="utf-8-sig")
    buckets.to_csv(C.OUT_DIR / "score_buckets.csv", encoding="utf-8-sig")
    yr.to_csv(C.OUT_DIR / "yearly.csv", encoding="utf-8-sig")
    res.join(reg[["score", "quadrant", "crisis", "target_weight"]]).to_csv(
        C.OUT_DIR / "daily_result.csv", encoding="utf-8-sig")
    plot(res, C.OUT_DIR / "backtest_chart.png")

    if not args.no_sensitivity:
        sens = sensitivity(df, start)
        sens.to_csv(C.OUT_DIR / "sensitivity.csv", index=False, encoding="utf-8-sig")
        print("■ 파라미터 민감도 (27개 조합, 샤프 순 상위 5 / 하위 3)")
        print(sens.head(5).to_string(index=False))
        print(sens.tail(3).to_string(index=False))
        print(f"  샤프 중앙값 {sens['샤프'].median():.2f}, 최저 {sens['샤프'].min():.2f}"
              " → 상위와 중앙값 차이가 작을수록 강건\n")

    print(f"결과 저장: {C.OUT_DIR}")


if __name__ == "__main__":
    main()
