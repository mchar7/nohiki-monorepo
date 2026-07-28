type SessionReset = () => void;

const sessionResets = new Set<SessionReset>();

function registerSessionReset(reset: SessionReset): () => void {
  sessionResets.add(reset);
  return (): void => {
    sessionResets.delete(reset);
  };
}

function resetUserSessionResources(): void {
  for (const reset of sessionResets) reset();
}

export { registerSessionReset, resetUserSessionResources };
