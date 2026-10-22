/** Keep the confirmation, API target and success message on the same action. */
export function userStatusAction(isActive: boolean) {
  return {
    next: !isActive,
    verb: isActive ? '封禁' : '解封',
    warning: isActive ? '该用户将立即无法登录。' : '',
  };
}
