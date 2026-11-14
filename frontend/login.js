// Firebase email + password sign-in. The ID token is exchanged for an HttpOnly session cookie by the
// server (/api/session); the browser keeps no Firebase credentials afterwards.
import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js';
import { getAuth, signInWithEmailAndPassword, signOut, setPersistence, inMemoryPersistence }
  from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js';

const form = document.querySelector('#login');
const button = document.querySelector('#submit');
const errorBox = document.querySelector('#error');

const params = new URLSearchParams(window.location.search);
const requested = params.get('next') || '/';
const next = requested.startsWith('/') && !requested.startsWith('//') && !requested.includes('\\') ? requested : '/';

const messages = {
  'auth/invalid-credential': 'Wrong email or password.',
  'auth/invalid-email': 'Enter a valid email address.',
  'auth/user-disabled': 'This account has been disabled.',
  'auth/too-many-requests': 'Too many attempts. Wait a few minutes and try again.',
  'auth/network-request-failed': 'Network error. Check your connection.',
};

let auth = null;
async function firebaseAuth() {
  if (auth) return auth;
  const config = await (await fetch('/firebase-config')).json();
  auth = getAuth(initializeApp(config));
  await setPersistence(auth, inMemoryPersistence);
  return auth;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.textContent = '';
  button.disabled = true;
  try {
    if (window.CryptoXConfig) {
      const hosted = await import("/hosted-auth.js");
      await hosted.login(document.querySelector("#email").value.trim(), document.querySelector("#password").value);
      window.location.replace(next);
      return;
    }
    const a = await firebaseAuth();
    const credential = await signInWithEmailAndPassword(a, document.querySelector('#email').value.trim(), document.querySelector('#password').value);
    const idToken = await credential.user.getIdToken();
    const response = await fetch('/api/session', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ idToken }),
    });
    await signOut(a);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `Sign-in failed (${response.status}).`);
    }
    window.location.replace(next);
  } catch (error) {
    errorBox.textContent = messages[error.code] || error.message || 'Sign-in failed.';
    button.disabled = false;
  }
});
