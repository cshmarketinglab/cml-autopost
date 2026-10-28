# CML 자동 발행 (쓰레드 + 인스타 캐러셀)

## 동작 흐름

```
06:30  [1. 매일 초안 생성]  Claude가 쓰레드 3개(+격일 캐러셀 7장) 작성 → 이미지 렌더링 → GitHub 이슈로 초안 도착 (메일/깃허브 앱 알림)
       ↓ 이슈에 댓글 /approve  (폰에서 가능)
08:10  쓰레드 공감글   발행
12:20  쓰레드 모집글   발행
19:10  인스타 캐러셀   발행 (격일)
20:40  쓰레드 공감글   발행
매월 1·11·21일  토큰 자동 연장
```

- 시간·주기·검수 모드·브랜드 문구는 전부 `config.yaml`에서 바꾼다.
- 글 톤·규칙은 `prompts/threads.md`, `prompts/carousel.md`에서 바꾼다.
- GitHub Actions 예약 실행은 수 분~30분 늦게 돌 수 있다. 정각 발행이 필요하면 이 방식은 안 맞는다.

---

## 세팅 순서 (처음 한 번, 약 1~2시간)

### STEP 1. GitHub 저장소 만들기
1. github.com 가입 → 우측 상단 `+` → New repository
2. 이름 `cml-autopost`, **Public** 선택 → Create
   - Public인 이유: 인스타 API는 이미지를 "공개 URL"로만 받는다. 공개 저장소면 무료로 해결되고 Actions 사용량도 무료.
   - 대신 발행 전 초안이 저장소에서 공개 상태로 보인다. 신경 쓰이면 Private로 만들고 이미지 호스팅(Cloudinary 등)을 붙여 `IMAGE_BASE_URL`을 지정해야 함.
3. 이 폴더 파일 전부 업로드: 저장소 화면 `uploading an existing file` → 압축 푼 폴더 내용 드래그 → Commit
   - `.github` 폴더가 숨김 폴더라 드래그에서 빠질 수 있다. 업로드 후 저장소에 `.github/workflows`가 보이는지 꼭 확인.
4. Settings → Actions → General → Workflow permissions → **Read and write permissions** 선택 → Save

### STEP 2. Claude API 키
1. console.anthropic.com 가입 → Billing에서 카드 등록 + 크레딧 충전 ($5면 몇 달 쓴다)
2. Settings → Limits에서 **월 사용 한도 $10** 걸어두기 (사고 방지)
3. API Keys → Create Key → 복사해 둠

### STEP 2-1. Pexels API 키 (캐러셀 사진용, 무료)
1. pexels.com 가입 → pexels.com/api → Your API Key → 용도에 "Instagram content automation for my marketing account" 정도 적고 발급 (즉시 발급)
2. 무료 한도: 시간당 200회, 월 20,000회 — 캐러셀 1개에 6~10회 쓰므로 여유 충분
3. 키가 없으면 캐러셀은 사진 없이 검정 배경으로 렌더된다 (발행은 정상 동작)

### STEP 3. 쓰레드 API 토큰
1. developers.facebook.com → 내 앱 → 앱 만들기 → 사용 사례에서 **Threads API 액세스** 선택
2. 사용 사례 → 권한에 `threads_basic`, `threads_content_publish` 추가
3. 앱 역할 → 역할 → **Threads 테스터**로 본인 쓰레드 계정 추가
4. 쓰레드 앱(웹) → 설정 → 계정 → 웹사이트 권한 → 초대 수락
5. 사용 사례 설정의 토큰 생성기에서 액세스 토큰 발급 → **장기 토큰(60일)**인지 확인
6. 아래 주소를 브라우저에 붙여넣어 user id 확인 (`토큰` 부분 교체)
   `https://graph.threads.net/v1.0/me?fields=id,username&access_token=토큰`

> 본인 계정에만 올리는 용도라 앱 심사(App Review) 없이 테스터 권한으로 동작한다.
> 메뉴 이름은 Meta가 자주 바꾼다. 화면이 다르면 "Threads API get access token" 공식 문서 기준으로 진행.

### STEP 4. 인스타그램 API 토큰
1. 인스타 계정을 **프로페셔널(비즈니스 또는 크리에이터)** 계정으로 전환 (이미 했으면 패스)
2. STEP 3에서 만든 앱(또는 새 앱)에 사용 사례 **Instagram API (Instagram 로그인)** 추가
3. 권한: `instagram_business_basic`, `instagram_business_content_publish`
4. 앱 역할 → **Instagram 테스터**로 본인 계정 추가 → 인스타 웹 설정 → 앱 및 웹사이트에서 초대 수락
5. API 설정 화면에서 계정 추가 → **토큰 생성** → 장기 토큰 복사
6. user id 확인: `https://graph.instagram.com/me?fields=user_id,username&access_token=토큰` → `user_id` 값 사용

### STEP 5. 토큰 자동 연장용 GitHub 토큰
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate
2. Repository access: `cml-autopost`만 선택
3. Permissions → Repository → **Secrets: Read and write**
4. 만료일은 최대로(1년). 만료되면 이것만 다시 발급

### STEP 6. Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | STEP 2 키 |
| `PEXELS_API_KEY` | STEP 2-1 키 |
| `THREADS_ACCESS_TOKEN` | STEP 3 토큰 |
| `THREADS_USER_ID` | STEP 3 id |
| `IG_ACCESS_TOKEN` | STEP 4 토큰 |
| `IG_USER_ID` | STEP 4 user_id |
| `GH_PAT` | STEP 5 토큰 |

### STEP 7. config.yaml 수정 (필수 2곳)
- `brand.handle` → 실제 계정 핸들
- `brand.cta` → 실제로 쓸 행동 유도 문구 (오픈프로필, 링크 등)

### STEP 8. 테스트
1. Actions 탭 → **1. 매일 초안 생성** → Run workflow (날짜 비우고 실행)
2. 2~4분 뒤 Issues 탭에 `[초안] 날짜` 이슈 도착 → 글·이미지 확인
3. 댓글 `/approve 1` → 1번 쓰레드가 예약 시간이 지났으면 즉시 발행됨 (아니면 예약 시간에)
4. 실제 쓰레드에 올라왔는지 확인. 실패하면 Actions → 해당 실행 로그의 ❌ 줄 확인
5. 캐러셀 테스트는 `config.yaml`의 `carousel_anchor_date`를 오늘로 바꾸고 생성 재실행(`force` 체크)

---

## 캐러셀 디자인

6~10장 (주제에 따라 Claude가 결정, 인스타 API 한도가 10장): 전면 사진 표지 → 폴라로이드 사진 + 본문 → 상단 사진 + 검정 본문 (반복) → 상단 사진 + 밝은 '오늘의 숙제' 장 → 로고 + 저장·팔로우 CTA

- 사진: Claude가 장마다 내용에 맞는 영어 검색어를 쓰고 Pexels에서 받아온다. 한 번 쓴 사진은 다시 안 쓴다(최근 600장 기록)
- 사진 톤 통일: 채도 살짝 낮춤 + 필름 그레인
- 로고·라벨·시리즈명(`동네 가게 마케팅 수업 N교시`)·아웃트로 문구는 `config.yaml`의 `design`에서 수정
- 색·글자 크기는 `templates/carousel.css`에서 수정
- 본문 글이 길면 글자 크기를 자동으로 줄이고, 그래도 넘치면 초안 이슈에 ⚠️ 표시
- Pexels 사진은 상업적 이용 무료, 출처 표기 의무는 없지만 권장 → 캡션 끝에 `Photos via Pexels` 자동 추가 (`photo_credit_in_caption`으로 끄기 가능)

## 검수 명령 (초안 이슈 댓글)

| 댓글 | 동작 |
|---|---|
| `/approve` | 전부 승인 |
| `/approve 1 3` | 1, 3번만 승인 |
| `/skip 2` | 2번 발행 안 함 |
| `/edit 2` + 줄바꿈 + 새 본문 | 2번 교체 후 승인 |
| `/caption` + 줄바꿈 + 새 캡션 | 캐러셀 캡션 교체 |

캐러셀 사진·이미지 문구가 마음에 안 들면: Actions → 1. 매일 초안 생성 → 날짜 입력 + `force` 체크로 재생성 (쓰레드 글도 같이 새로 생성됨)

- 예약 시각 전 승인 → 그 시각에 발행 / 지난 뒤 승인 → 즉시 발행 / 승인 안 하면 안 올라감
- 저장소 주인 계정의 댓글만 반영된다
- 2~3주 써보고 품질이 안정되면 `auto_approve: true`로 바꾸면 완전 자동

## 비용

| 항목 | 월 비용 |
|---|---|
| Claude API (Sonnet, 월 쓰레드 90개 + 캐러셀 15개) | 약 1~3달러 |
| GitHub Actions (공개 저장소) | 0원 |
| Threads / Instagram API | 0원 |

## 문제 생겼을 때

| 증상 | 원인 / 해결 |
|---|---|
| 발행 실패 `OAuthException` / 토큰 만료 | 토큰 연장이 실패한 것. STEP 3·4 토큰 재발급 후 Secret 교체 |
| 인스타 `image_url` 오류 | 저장소가 Private이거나 이미지 커밋 전에 발행 시도. Public 확인 |
| 이슈가 안 옴 | Settings → Actions 권한이 Read and write인지 확인 |
| 같은 소재 반복 | `config.yaml`의 `empathy_pillars`, `carousel_topics`에 소재 추가 |
| 60일 넘게 저장소 활동 없으면 예약 실행 정지 | 봇이 매일 커밋하므로 보통 문제없음. 멈추면 Actions에서 다시 Enable |

## 로컬 테스트 (선택)
```
pip install -r requirements.txt && python -m playwright install chromium
cd src && MOCK_LLM=1 MOCK_PHOTOS=/사진폴더 PYTHONPATH=../tests DRY_RUN=1 GITHUB_REPOSITORY=me/repo python generate.py 2026-10-28
```
