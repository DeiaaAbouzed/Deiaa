export const STAFF = ['admin', 'trainer', 'pharmacist'];
export const MANAGERS = ['admin', 'trainer'];
export const ADMIN = ['admin'];
export const EVERYONE = ['admin', 'trainer', 'pharmacist', 'trainee'];

export const state = {
  me: null,
};

export function role() {
  return state.me ? state.me.user.role : null;
}

export function hasRole(roles) {
  return Boolean(state.me) && roles.includes(state.me.user.role);
}

export function homeRoute() {
  return hasRole(STAFF) ? 'read' : 'academy';
}
