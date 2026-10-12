// Live context is separate from the readable archive and from saved drafts.
export function createAssistantConversations(newId = () => crypto.randomUUID()) {
  const scopes = new Map();
  function id(scope) {
    if (!scopes.has(scope)) {
      if (scopes.size >= 30) scopes.delete(scopes.keys().next().value);
      scopes.set(scope, newId());
    }
    return scopes.get(scope);
  }
  return { id, reset(scope) { scopes.delete(scope); return id(scope); } };
}
