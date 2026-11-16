"""
대시보드용 데이터 내보내기
- backtest.py 실행 후 실행: data/merged_daily.csv, output/*.csv 를 읽어
  웹 대시보드(index.html)가 읽는 data/dashboard.json 한 파일로 만든다.

사용법:
    python data_collector.py
    python backtest.py
    python export_site.py
"""
import json
import math
from datetime import datetime, timezone

import pandas as pd

import config as C
from regime import build_features, compute_regime

OUT_JSON = C.BASE_DIR / "data" / "dashboard.json"

INDICATOR_META = {
    # key: (이름, 원자료 컬럼, 단위, 변화 기준, 퍼센트 변환 여부)
    "rate":   ("미국 2년물 금리", "us2y", "%", "3개월 변화(%p)", False),
    "krw":    ("원/달러 환율", "usdkrw", "원", "3개월 변화율(%)", True),
    "semi":   ("필라델피아 반도체지수", "sox", "pt", "3개월 변화율(%)", True),
    "copper": ("구리 선물", "copper", "$/lb", "3개월 변화율(%)", True),
    "credit": ("미국 하이일드 스프레드", "hy_oas", "%p", "1개월 변화(%p)", False),
}

SUMMARY_COLS = {"CAGR(%)": "cagr", "변동성(%)": "vol", "샤프": "sharpe", "MDD(%)": "mdd", "칼마": "calmar",
                "최종배수": "multiple", "연 회전율(배)": "turnover", "평균 주식비중(%)": "avg_weight",
                "연 비용(%)": "cost"}


def clean(v):
    """JSON에 넣을 수 있는 값으로 변환 (NaN → None)"""
    if v is None:
        return None
    if isinstance(v, (bool,)):
        return v
    try:
        import numpy as np
        if isinstance(v, np.bool_):
            return bool(v)
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating, float)):
            return None if math.isnan(float(v)) else float(v)
    except ImportError:
        pass
    return v


def records(df: pd.DataFrame, rnd: int = 4):
    out = []
    for row in df.to_dict(orient="records"):
        r = {}
        for k, v in row.items():
            v = clean(v)
            if isinstance(v, float):
                v = round(v, rnd)
            r[k] = v
        out.append(r)
    return out


def last_valid(series: pd.Series):
    s = series.dropna()
    return (str(s.index[-1].date()), float(s.iloc[-1])) if len(s) else (None, None)


def main():
    m = pd.read_csv(C.DATA_FILE, index_col="date", parse_dates=True)
    d = pd.read_csv(C.OUT_DIR / "daily_result.csv", index_col=0, parse_dates=True)
    reg = compute_regime(m)
    feat = build_features(m)
    w = C.REGIME["weights"]
    last = m.index[-1]

    # ---- 현재 신호
    held = float(d["w_equity"].iloc[-1]) * 100
    score_hist = reg["score"].dropna()
    cur = {
        "as_of": str(last.date()),
        "score": round(float(reg["score"].loc[last]), 2),
        "quadrant": str(reg["quadrant"].loc[last]),
        "crisis": bool(reg["crisis"].loc[last]),
        "target_weight": round(float(reg["target_weight"].loc[last]) * 100, 1),
        "held_weight": round(held, 1),
        "score_pctile": round(float((score_hist < reg["score"].loc[last]).mean() * 100), 1),
        "kodex_from_peak": round(float((m["tradable"].iloc[-1] / m["tradable"].max() - 1) * 100), 1),
    }

    # ---- 점수 구성 지표
    ind = []
    for k, (name, col, unit, label, pct) in INDICATOR_META.items():
        zc = f"z_{k}"
        if zc not in reg or col not in m:
            continue
        z = reg[zc].loc[last]
        ch = feat[k].loc[last]
        ind.append({
            "key": k, "name": name, "level": round(float(m[col].loc[last]), 2), "unit": unit,
            "change_label": label,
            "change": None if pd.isna(ch) else round(float(ch * 100 if pct else ch), 2),
            "z": None if pd.isna(z) else round(float(z), 2),
            "weight": w[k],
            "contribution": None if pd.isna(z) else round(float(w[k] * z), 2),
            "data_date": last_valid(m[col])[0],
        })

    # ---- 참고 지표
    ref_spec = [("VIX", "vix", "위기 필터 기준 30", 2), ("미국 장단기 금리차(10년-2년)", "t10y2y", "%p, 음수면 침체 선행 신호", 2),
                ("WTI 유가", "wti", "$/배럴", 2), ("미국 10년물 금리", "us10y", "%", 2),
                ("S&P 500", "spx", "pt", 1), ("KODEX 200", "kodex200", "원", 0)]
    ref = [{"name": n, "level": round(float(m[c].loc[last]), r), "note": note}
           for n, c, note, r in ref_spec if c in m and pd.notna(m[c].loc[last])]

    # ---- 주간 시계열
    wk = d.resample("W-FRI").last()
    dd_s = ((d["nav_strategy"] / d["nav_strategy"].cummax() - 1) * 100).resample("W-FRI").min()
    dd_b = ((d["nav_buyhold"] / d["nav_buyhold"].cummax() - 1) * 100).resample("W-FRI").min()
    weekly = pd.DataFrame({
        "date": wk.index.strftime("%Y-%m-%d"),
        "nav_strategy": wk["nav_strategy"].round(4).values,
        "nav_buyhold": wk["nav_buyhold"].round(4).values,
        "nav_fixed60": wk["nav_fixed60"].round(4).values,
        "dd_strategy": dd_s.round(2).values,
        "dd_buyhold": dd_b.round(2).values,
        "equity_weight": (wk["w_equity"] * 100).round(1).values,
        "score": wk["score"].round(2).values,
    }).dropna()

    # ---- 백테스트 리포트
    rd = lambda n: pd.read_csv(C.OUT_DIR / f"{n}.csv", encoding="utf-8-sig")
    summary = rd("summary").rename(columns={"Unnamed: 0": "strategy", **SUMMARY_COLS})
    yearly = rd("yearly").rename(columns={"date": "year", "레짐 전략(%)": "strategy", "코스피200(%)": "kospi200",
                                          "평균 주식비중(%)": "avg_weight", "초과(%p)": "excess"})
    regime_report = rd("regime_report").rename(columns={"관측일수": "days", "비중(%)": "share",
                                                        "평균 21일 수익률(%)": "fwd_ret", "상승확률(%)": "up_prob",
                                                        "변동성(%)": "vol"})
    buckets = rd("score_buckets").rename(columns={"점수 평균": "score_mean", "평균 21일 수익률(%)": "fwd_ret",
                                                  "상승확률(%)": "up_prob"})
    sens_path = C.OUT_DIR / "sensitivity.csv"
    sens = rd("sensitivity").rename(columns=SUMMARY_COLS) if sens_path.exists() else pd.DataFrame()

    first = reg["target_weight"].first_valid_index()
    out = {
        "meta": {
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": str(last.date()),
            "period_start": str(d.index[0].date()) if first is None else str(max(first, d.index[0]).date()),
            "period_end": str(d.index[-1].date()),
            "used_vars": reg.attrs.get("used_vars", []),
            "rebalance": C.BACKTEST["rebalance"],
        },
        "current_signal": [cur],
        "indicators": ind,
        "reference": ref,
        "summary": records(summary),
        "weekly_series": records(weekly),
        "yearly": records(yearly),
        "regime_report": records(regime_report),
        "score_buckets": records(buckets),
        "sensitivity": records(sens),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {OUT_JSON} ({OUT_JSON.stat().st_size / 1024:.0f} KB) / 기준일 {cur['as_of']} / 점수 {cur['score']}")


if __name__ == "__main__":
    main()
