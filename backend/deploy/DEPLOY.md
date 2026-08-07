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

## 3. nginx + TLS (nip.io — 도메인 구매/DNS 관리 없이 바로 사용)

도메인을 따로 사지 않고, IP를 그대로 호스트명으로 바꿔주는 무료 서비스인
[nip.io](https://nip.io)를 쓴다. `1-2-3-4.nip.io`는 자동으로 `1.2.3.4`를 가리키므로
계정 생성도, DNS 레코드 설정도 필요 없다.

```bash
# 1) 이 인스턴스의 퍼블릭 IP 확인
PUBLIC_IP=$(curl -4 -s ifconfig.me)
DOMAIN="$(echo $PUBLIC_IP | tr '.' '-').nip.io"
echo "$DOMAIN"   # 예: 3-38-123-45.nip.io — 이 값을 기억해둔다

# 2) nginx 설정
sudo cp etiquette-api.nginx.conf /etc/nginx/sites-available/etiquette-api
sudo sed -i "s/YOUR_DOMAIN/$DOMAIN/" /etc/nginx/sites-available/etiquette-api
sudo ln -s /etc/nginx/sites-available/etiquette-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 3) TLS 인증서 발급 (443 블록을 certbot이 자동으로 추가)
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m you@example.com
```

배포 후 `https://$DOMAIN/health`가 응답하면 완료. 이 `https://$DOMAIN`이
프론트엔드의 `VITE_API_URL`(GitHub 저장소 Settings → Secrets and variables →
Actions → Variables)에 넣을 값이다.

## 4. ⚠️ 인스턴스 재시작 시 도메인이 바뀌는 문제

운영 가이드대로 인스턴스를 껐다 켜면 퍼블릭 IP가 매번 바뀌고, nip.io 방식은 IP를
그대로 도메인에 쓰므로 **도메인 자체도 매번 바뀐다**. 재시작할 때마다:
1. 위 1~3단계를 다시 실행해서 새 `$DOMAIN`으로 nginx/인증서를 재설정하고
2. GitHub 저장소의 `VITE_API_URL` 값을 새 도메인으로 갱신한 뒤 Actions를 재실행(재배포)한다.

번거로우니 다음을 먼저 확인하는 걸 추천한다:
1. **강사/보조 강사에게 Elastic IP(고정 IP) 배정이 가능한지 문의** — 되면 IP가 안 바뀌니
   nip.io 도메인도 영구적으로 고정되어 이 문제가 통째로 사라진다.
2. 안 되면, 데모/제출 기간 동안은 되도록 인스턴스를 끄지 않고 유지해서 재시작 횟수를
   최소화한다 (예산은 한 달 기준으로 계획되어 있으니, 매번 껐다 켜는 것보다 단순함).
3. 나중에 실제 도메인을 구매하게 되면, 그 도메인의 A 레코드를 인스턴스 IP로 갱신하는
   방식으로 넘어가면 재시작마다 인증서를 새로 받을 필요도 없어진다(도메인은 고정, IP만 갱신).

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
