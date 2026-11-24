// Browser AI (Desert Ant Redact, Gist, Emo). Stub: everything reports unavailable.
// Every function resolves and never rejects.

export async function startBrowserAI() {
  return { redact: false, gist: false, emo: false };
}

export async function suggestEmoji(name, description) {
  return null;
}

export async function analyzeFile(fullFile) {
  return null;
}

export async function runPrivacyPass(cards, { apiBase, signal, onUpdate } = {}) {
  return { status: 'unavailable', done: 0, skipped: 0, failed: 0 };
}
