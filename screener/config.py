from datetime import date

UNIVERSE_SIZE = 250
FISCAL_MONTH = 12

EXCLUDED_SECTORS = [
    "은행", "증권", "보험", "기타금융",
    "지주회사", "금융지주",
]

QUALITY_THRESHOLDS = {
    "roe_min": 0.08,
    "debt_ratio_max": 1.50,
    "current_ratio_min": 1.00,
    "piotroski_min": 6,
}

SELECTION_COUNT = 20

DART_BASE_URL = "https://opendart.fss.or.kr/api"
OUTPUT_PATH = "docs/data/latest.json"

DART_ACCOUNT_ALIASES = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출", "수입금액"],
    "operating_profit": ["영업이익", "영업손익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)"],
    "total_equity": ["자본총계"],
    "total_assets": ["자산총계"],
    "total_liabilities": ["부채총계"],
    "current_assets": ["유동자산"],
    "current_liabilities": ["유동부채"],
    "operating_cash_flow": [
        "영업활동현금흐름", "영업활동으로인한현금흐름",
        "영업활동현금흐름(손실)", "영업활동으로 인한 현금흐름",
    ],
    "long_term_debt": ["비유동부채", "장기차입금"],
    "gross_profit": ["매출총이익", "매출총손익"],
}


def get_target_fiscal_year() -> int:
    today = date.today()
    # Annual reports for FY N are due by end of March N+1
    return today.year - 1 if today.month >= 4 else today.year - 2
