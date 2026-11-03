import { loginHref, sanitizeReturnTo } from '@/lib/navigation';

const RETURN_TO_KEY = 'topiceye.oauth.returnTo';
type ReturnStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function rememberOauthReturnTo(storage: ReturnStorage, path: string) {
  storage.setItem(RETURN_TO_KEY, sanitizeReturnTo(path));
}

export function consumeOauthReturnTo(storage: ReturnStorage): string {
  const path = sanitizeReturnTo(storage.getItem(RETURN_TO_KEY));
  storage.removeItem(RETURN_TO_KEY);
  return path;
}

/** 登录失败后重试，仍保留此次 OAuth 的原目标。 */
export function oauthRetryLoginHref(storage: ReturnStorage): string {
  return loginHref(consumeOauthReturnTo(storage));
}
