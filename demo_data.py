"""
가상 데이터 생성기 (인터넷 없이 코드 동작을 확인하는 용도)
- 실제 시장과 무관한 합성 데이터입니다. 여기서 나온 성과 수치는 의미가 없습니다.
- 매크로 변수와 주가 사이에 '약한' 연관을 일부러 넣어 파이프라인이 작동하는지만 봅니다.
"""
import numpy as np
import pandas as pd


def make_demo(start="2005-01-03", end="2026-10-30", seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end)
    n = len(idx)

    def ar_walk(level, vol, kappa=0.0, mean=None):
        x = np.empty(n)
        x[0] = level
        for i in range(1, n):
            drift = kappa * ((mean if mean is not None else level) - x[i - 1])
            x[i] = x[i - 1] + drift + rng.normal(0, vol)
        return x

    us2y = np.clip(ar_walk(3.0, 0.05, 0.0005, 2.5), 0.05, None)
    usdkrw = 1100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    hy = np.clip(ar_walk(4.5, 0.08, 0.003, 4.5), 2.5, None)
    vix = np.clip(12 + 3 * (hy - 3.0) + rng.normal(0, 2, n), 9, 80)
    sox = 400 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, n)))
    copper = 3.0 * np.exp(np.cumsum(rng.normal(0.0001, 0.014, n)))

    # 주가: 매크로 변화(과거 값)에 약하게 반응하도록 구성
    d_rate = pd.Series(us2y).diff(63).shift(1).fillna(0).values
    d_krw = pd.Series(usdkrw).pct_change(63).shift(1).fillna(0).values
    d_hy = pd.Series(hy).diff(21).shift(1).fillna(0).values
    mu = 0.0002 - 0.0004 * d_rate - 0.01 * d_krw - 0.0008 * d_hy
    vol = 0.011 + 0.0008 * np.clip(hy - 3.0, 0, None)
    ret = mu + vol * rng.standard_normal(n)
    kospi200 = 150 * np.exp(np.cumsum(ret))

    df = pd.DataFrame({
        "kospi200": kospi200, "tradable": kospi200, "kodex200": kospi200 * 100,
        "foreign_net": rng.normal(0, 2e11, n),
        "us2y": us2y, "us10y": us2y + 0.8 + rng.normal(0, 0.05, n),
        "usdkrw": usdkrw, "hy_oas": hy, "vix": vix, "sox": sox, "copper": copper,
        "cd91": np.clip(us2y * 0.8 + 0.5, 0.5, None),
    }, index=idx)
    df["t10y2y"] = df["us10y"] - df["us2y"]
    df.index.name = "date"
    return df
