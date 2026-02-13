# Keyword Automation (Naver → Google Ads)

요청하신 수집/필터링 흐름(지식백과 → 연관키워드 → 블로그 문서수 → 포화도 → Google Ads 단가)을 자동화하는 스크립트입니다.

## 포함된 자동화 단계

1. 네이버 지식백과 카테고리 페이지에서 키워드 수집
2. 네이버 검색광고 API(`keywordstool`)로 연관 키워드 확장
3. 네이버 뷰(블로그) 검색 결과에서 문서 수 수집
4. 포화도(`blog_docs / (pc+mobile volume)`) 계산
5. 경쟁도/검색량 기준으로 1차 필터
6. (옵션) Google Ads API로 월검색량/경쟁/상단입찰가 보강
7. CSV 결과 저장

## 파일

- `keyword_pipeline.py`: 메인 파이프라인

## 사전 준비

### Python 패키지

```bash
pip install google-ads  # Google Ads 단계도 사용할 경우
```

### 네이버 검색광고 API 키

아래 환경변수 또는 CLI 옵션으로 전달:

- `NAVER_CUSTOMER_ID`
- `NAVER_ACCESS_KEY`
- `NAVER_SECRET_KEY`

### Google Ads API(선택)

- `google-ads.yaml` 준비
- `GOOGLE_ADS_CUSTOMER_ID` 설정 또는 `--google-customer-id` 전달

## 실행 예시

```bash
python keyword_pipeline.py \
  --category-urls "https://terms.naver.com/list.naver?cid=40942&categoryId=32182" \
  --pages-per-category 30 \
  --include-source-keywords \
  --max-competition 0.6 \
  --min-total-volume 30 \
  --output-dir output
```

Google Ads까지 포함:

```bash
python keyword_pipeline.py \
  --category-urls "https://terms.naver.com/list.naver?cid=40942&categoryId=32182" \
  --pages-per-category 30 \
  --enable-google-ads \
  --google-customer-id "1234567890"
```

## 출력

- `output/keywords_raw_<timestamp>.csv`
- `output/keywords_filtered_<timestamp>.csv`

컬럼:
- `keyword`, `source`
- `naver_monthly_pc`, `naver_monthly_mobile`, `naver_competition`
- `naver_blog_docs`, `saturation_score`
- `google_avg_monthly_searches`, `google_competition`
- `google_top_bid_low_micros`, `google_top_bid_high_micros`

## 주의사항

- 네이버 페이지 DOM 구조는 자주 바뀌므로 `--knowledge-selector` 조정이 필요할 수 있습니다.
- 크롤링 시 요청 간 딜레이를 두고 동작하게 작성했지만, 운영 시에는 반드시 각 서비스 정책/약관 준수 필요합니다.
- Google 키워드플래너 UI 자동화 대신 공식 API 연동 방식으로 구성했습니다.
