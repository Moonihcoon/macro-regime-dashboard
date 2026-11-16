"""
2단계: 매크로 레짐 엔진
- 입력: data_collector.py 가 만든 merged_daily.csv (이미 point-in-time 정렬됨)
- 출력: 일별 피처, 레짐 점수, 4국면 라벨, 위기 플래그, 목표 주식 비중

모든 계산은 '과거 데이터만' 사용합니다 (롤링 z-score, 미래 참조 없음).
"""
import numpy as np
import pandas as pd

import config as C


def rolling_z(s: pd.Series, window: int, min_periods: int, clip: float) -> pd.Series:
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return ((s - mu) / sd).clip(-clip, clip)


def build_features(df: pd.DataFrame, p: dict = None) -> pd.DataFrame:
    p = p or C.REGIME
    m, s = p["mom_window"], p["short_window"]
    f = pd.DataFrame(index=df.index)

    # 금리: 3개월 변화폭(%p) - 금리는 수준보다 '방향'이 주가에 중요
    f["rate"] = df["us2y"].diff(m)
    # 환율: 3개월 변화율 (원/달러 상승 = 원화 약세)
    f["krw"] = df["usdkrw"].pct_change(m, fill_method=None)
    # 반도체 업황: 3개월 모멘텀 (코스피 시총 비중 최대 업종)
    f["semi"] = df["sox"].pct_change(m, fill_method=None) if "sox" in df else np.nan
    # 중국 경기 대리: 구리 3개월 모멘텀
    f["copper"] = df["copper"].pct_change(m, fill_method=None) if "copper" in df else np.nan
    # 신용위험: 하이일드 스프레드 1개월 변화폭(%p)
    f["credit"] = df["hy_oas"].diff(s)
    # 참고 지표 (점수에는 미포함, 분석용)
    if "t10y2y" in df:
        f["curve"] = df["t10y2y"]
    if "foreign_net" in df:
        f["foreign_20d"] = df["foreign_net"].rolling(20).sum()
    return f


def compute_regime(df: pd.DataFrame, p: dict = None) -> pd.DataFrame:
    p = p or C.REGIME
    feat = build_features(df, p)
    out = feat.copy()

    score = pd.Series(0.0, index=df.index)
    used = pd.Series(0.0, index=df.index)
    used_vars = []
    for name, w in p["weights"].items():
        if name not in feat or feat[name].isna().all():
            continue
        z = rolling_z(feat[name], p["z_window"], p["z_min_periods"], p["z_clip"])
        out[f"z_{name}"] = z
        used_vars.append(name)
        score = score.add(w * z.fillna(0.0))
        used = used.add(abs(w) * z.notna())
    # 사용 가능한 변수가 일부만 있어도 점수 스케일이 유지되도록 정규화
    total_w = sum(abs(w) for w in p["weights"].values())
    out["score"] = score * total_w / used.replace(0, np.nan)
    # 변수 5개가 모두 같은 방향이면 크게, 엇갈리면 0 근처 (통상 -4 ~ +4)

    # 4국면: 금리 방향 × 달러(원/달러) 방향
    up_rate = feat["rate"] > 0
    up_usd = feat["krw"] > 0
    out["quadrant"] = np.select(
        [~up_rate & ~up_usd, ~up_rate & up_usd, up_rate & ~up_usd, up_rate & up_usd],
        ["Q1 금리↓달러↓(최적)", "Q2 금리↓달러↑(경기우려)",
         "Q3 금리↑달러↓(회복)", "Q4 금리↑달러↑(최악)"], default="N/A")
    out.loc[feat["rate"].isna() | feat["krw"].isna(), "quadrant"] = "N/A"

    # 위기 필터
    crisis = pd.Series(False, index=df.index)
    if "vix" in df:
        crisis |= df["vix"] > p["vix_crisis"]
    crisis |= feat["credit"] > p["hy_jump_crisis"]
    out["crisis"] = crisis

    # 목표 주식 비중
    w = (p["base_weight"] + p["slope"] * out["score"]).clip(p["min_weight"], p["max_weight"])
    w = w.where(~crisis, np.minimum(w, p["crisis_cap"]))
    out["target_weight"] = w.where(out["score"].notna())
    out.attrs["used_vars"] = used_vars
    return out


def regime_report(df: pd.DataFrame, reg: pd.DataFrame, price_col="tradable",
                  horizon: int = 21) -> pd.DataFrame:
    """국면별 '다음 1개월' 코스피200 수익률 통계 → 레짐 정의가 의미 있는지 검증"""
    fwd = df[price_col].pct_change(horizon, fill_method=None).shift(-horizon)
    t = pd.DataFrame({"quadrant": reg["quadrant"], "crisis": reg["crisis"], "fwd": fwd}).dropna()
    t = t[t["quadrant"] != "N/A"]
    g = t.groupby("quadrant")["fwd"]
    rep = pd.DataFrame({
        "관측일수": g.size(),
        "비중(%)": (g.size() / len(t) * 100).round(1),
        f"평균 {horizon}일 수익률(%)": (g.mean() * 100).round(2),
        "상승확률(%)": (g.apply(lambda x: (x > 0).mean()) * 100).round(1),
        "변동성(%)": (g.std() * 100).round(2),
    })
    c = t.groupby("crisis")["fwd"].mean() * 100
    rep.attrs["crisis_fwd"] = c.round(2).to_dict()
    return rep


def score_bucket_report(df, reg, price_col="tradable", horizon=21, n=5):
    """레짐 점수 5분위별 다음 1개월 수익률 → 점수가 단조롭게 증가하는지 확인"""
    fwd = df[price_col].pct_change(horizon, fill_method=None).shift(-horizon)
    t = pd.DataFrame({"score": reg["score"], "fwd": fwd}).dropna()
    t["bucket"] = pd.qcut(t["score"], n, labels=[f"Q{i + 1}" for i in range(n)])
    g = t.groupby("bucket", observed=True)["fwd"]
    return pd.DataFrame({
        "점수 평균": t.groupby("bucket", observed=True)["score"].mean().round(2),
        f"평균 {horizon}일 수익률(%)": (g.mean() * 100).round(2),
        "상승확률(%)": (g.apply(lambda x: (x > 0).mean()) * 100).round(1),
    })
