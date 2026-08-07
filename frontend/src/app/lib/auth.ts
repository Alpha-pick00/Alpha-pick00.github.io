import { API_URL, ApiError } from './api';

export type AuthProvider = 'google' | 'kakao' | 'naver';

export interface AuthUser {
  provider: AuthProvider;
  provider_user_id: string;
  email: string | null;
  name: string | null;
  picture: string | null;
}

const TOKEN_KEY = 'etiquette-session-token';
const OAUTH_STATE_KEY = 'etiquette-oauth-state';

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function storeToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function parseAuthResponse(response: Response): Promise<AuthUser> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail || `로그인에 실패했습니다 (${response.status})`);
  }
  const data = await response.json();
  storeToken(data.token);
  return data.user;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = getStoredToken();
  if (!token) return null;
  const response = await fetch(`${API_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    clearToken();
    return null;
  }
  return response.json();
}

export async function loginWithGoogle(credential: string): Promise<AuthUser> {
  const response = await fetch(`${API_URL}/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  });
  return parseAuthResponse(response);
}

async function loginWithCode(
  provider: 'kakao' | 'naver',
  code: string,
  redirectUri: string,
  state: string | null
): Promise<AuthUser> {
  const response = await fetch(`${API_URL}/auth/${provider}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, redirect_uri: redirectUri, state }),
  });
  return parseAuthResponse(response);
}

function getRedirectUri(): string {
  // 쿼리스트링/해시 없이 앱의 기본 URL만 사용 — 소셜 로그인 콘솔에 등록할 값과 동일해야 한다.
  return `${window.location.origin}${window.location.pathname}`;
}

function startOAuthRedirect(provider: 'kakao' | 'naver', authorizeUrl: string, clientId: string): void {
  const state = `${provider}_${crypto.randomUUID()}`;
  sessionStorage.setItem(OAUTH_STATE_KEY, state);
  const redirectUri = getRedirectUri();

  const url = new URL(authorizeUrl);
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('redirect_uri', redirectUri);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('state', state);
  window.location.href = url.toString();
}

export function startKakaoLogin(): void {
  const clientId = import.meta.env.VITE_KAKAO_CLIENT_ID;
  if (!clientId) {
    alert('카카오 로그인이 아직 설정되지 않았습니다.');
    return;
  }
  startOAuthRedirect('kakao', 'https://kauth.kakao.com/oauth/authorize', clientId);
}

export function startNaverLogin(): void {
  const clientId = import.meta.env.VITE_NAVER_CLIENT_ID;
  if (!clientId) {
    alert('네이버 로그인이 아직 설정되지 않았습니다.');
    return;
  }
  startOAuthRedirect('naver', 'https://nid.naver.com/oauth2.0/authorize', clientId);
}

/** 카카오/네이버 리다이렉트로 돌아왔을 때(쿼리에 code/state가 있을 때) 로그인을 완료 처리한다.
 * 콜백이 아니면 null을 반환하고 아무 것도 하지 않는다. */
export async function handleOAuthCallback(): Promise<AuthUser | null> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');
  if (!code || !state) return null;

  // 재조회(새로고침) 시 code를 재사용하지 않도록 URL을 즉시 정리한다.
  window.history.replaceState({}, '', window.location.pathname + window.location.hash);

  const savedState = sessionStorage.getItem(OAUTH_STATE_KEY);
  sessionStorage.removeItem(OAUTH_STATE_KEY);
  if (state !== savedState) return null; // CSRF 불일치 또는 오래된 콜백

  const provider = state.startsWith('kakao_') ? 'kakao' : state.startsWith('naver_') ? 'naver' : null;
  if (!provider) return null;

  return loginWithCode(provider, code, getRedirectUri(), state);
}

// --- Google Identity Services ---

interface GoogleCredentialResponse {
  credential: string;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
          }) => void;
          renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

let gisScriptPromise: Promise<void> | null = null;

function loadGoogleIdentityScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (gisScriptPromise) return gisScriptPromise;
  gisScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Google Identity Services 로드에 실패했습니다.'));
    document.head.appendChild(script);
  });
  return gisScriptPromise;
}

export async function renderGoogleButton(
  el: HTMLElement,
  onCredential: (credential: string) => void
): Promise<void> {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  if (!clientId) return;

  await loadGoogleIdentityScript();
  window.google!.accounts.id.initialize({
    client_id: clientId,
    callback: (response) => onCredential(response.credential),
  });
  window.google!.accounts.id.renderButton(el, {
    type: 'standard',
    theme: 'outline',
    size: 'large',
    shape: 'pill',
    width: 260,
  });
}
