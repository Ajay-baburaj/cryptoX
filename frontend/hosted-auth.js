import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js';
import { getAuth, setPersistence, browserSessionPersistence, signInWithEmailAndPassword, signOut }
  from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js';
const config = window.CryptoXConfig;
const auth = getAuth(initializeApp(config.firebase, 'hosted-auth'));
const ready = (async () => { await setPersistence(auth, browserSessionPersistence); await auth.authStateReady(); })();
export async function requireUser() {
  await ready;
  if (!auth.currentUser) location.replace('/login');
  return auth.currentUser;
}
export async function apiFetch(path, options = {}) {
  if (!path.startsWith('/api/')) throw new Error('Invalid API path');
  const user = await requireUser();
  if (!user) throw new Error('Sign in required');
  const send = async force => {
    const headers = new Headers(options.headers);
    headers.set('Authorization', `Bearer ${await user.getIdToken(force)}`);
    return fetch(config.apiBase + path, { ...options, headers, credentials: 'omit' });
  };
  let response = await send(false);
  if (response.status === 401) response = await send(true);
  if (response.status === 401 || response.status === 403) {
    await signOut(auth);
    location.replace('/login');
  }
  return response;
}
export async function login(email, password) {
  await ready;
  await signInWithEmailAndPassword(auth, email, password);
  try {
    const response = await apiFetch('/api/ob1h');
    if (!response.ok) throw new Error('Dashboard access could not be verified.');
  } catch (error) { await signOut(auth); throw error; }
}
export async function logout() { await signOut(auth); location.replace('/login'); }
