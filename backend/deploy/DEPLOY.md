# 백엔드 배포 (GPU 인스턴스, Ubuntu 24.04)

프론트엔드(GitHub Pages)는 그대로 두고, FastAPI 백엔드만 이 인스턴스에서 Docker로 띄운다.
열려 있는 포트는 22/80/443뿐이므로 nginx가 80/443을 받아 컨테이너의 8000번으로 프록시한다.

## 1. 최초 1회 설정

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # 이후 재접속 필요

# nginx + certbot
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx

# 저장소
git clone https://github.com/Cherry-Pick00/Etiquette.git
cd Etiquette/backend
cp .env.example .env
vi .env   # 실제 API 키 채워넣기 (이 파일은 git에 올라가지 않음)
```

Google Merchant를 쓴다면 서비스 계정 JSON 키를 `deploy/secrets/service-account.json`
에 두고, `.env`의 `GOOGLE_SERVICE_ACCOUNT_FILE`은 컨테이너 내부 경로인
`/secrets/service-account.json`으로 적는다. 안 쓰면 비워둬도 됨 (자동으로 기능만 비활성화).

## 2. 백엔드 실행

```bash
cd deploy
docker compose up -d --build
curl http://127.0.0.1:8000/health   # {"status":"ok"} 확인
```

## 3. nginx + TLS

```bash
sudo cp etiquette-api.nginx.conf /etc/nginx/sites-available/etiquette-api
sudo vi /etc/nginx/sites-available/etiquette-api   # YOUR_DOMAIN을 실제 도메인으로 교체
sudo ln -s /etc/nginx/sites-available/etiquette-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d YOUR_DOMAIN   # 443/HTTPS 블록을 자동으로 추가해줌
```

배포 후 `https://YOUR_DOMAIN/health`가 응답하면 완료.
프론트엔드가 호출할 API_URL을 이 도메인으로 맞춰준다.

## 4. ⚠️ 인스턴스 재시작 시 DNS가 바뀌는 문제

운영 가이드대로 인스턴스를 껐다 켜면 퍼블릭 DNS/IP가 매번 바뀐다. 그러면:
- nginx의 `server_name`, certbot 인증서, 프론트엔드의 API_URL이 전부 깨진다.

권장 순서:
1. **가장 먼저 강사/보조 강사에게 Elastic IP(고정 IP) 배정이 가능한지 문의** — 되면 이 문제가 통째로 사라진다.
2. 안 되면 본인이 관리하는 도메인(서브도메인)의 A 레코드를 직접 소유해서, 인스턴스를 켤 때마다
   `deploy/update-dns.sh` 같은 스크립트로 그 도메인의 A 레코드만 새 IP로 갱신 (Cloudflare 등은 API로 가능).
   도메인 자체는 안 바뀌므로 인증서도 그대로 유효하다.
3. 둘 다 여의치 않다면, 데모/제출 기간 동안은 되도록 인스턴스를 끄지 않고 유지해서 재시작 횟수를 최소화한다
   (예산은 한 달 기준으로 계획되어 있으니, 매번 껐다 켜는 것보다 이 방식이 오히려 운영이 단순함).

## 5. 코드 업데이트할 때

```bash
cd ~/Etiquette
git pull
cd backend/deploy
docker compose up -d --build
```

## 6. CORS

`app/main.py`에 `https://cherry-pick00.github.io`와 로컬 개발 origin만 허용해뒀다.
커스텀 도메인으로 프론트를 옮기면 `allow_origins`에 그 도메인도 추가해야 브라우저에서 호출 가능.
