const apiBase = window.location.origin;

async function postJson(path, payload) {
  try {
    await fetch(`${apiBase}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    // Best-effort sync; ignore errors to avoid breaking UX.
  }
}

export async function clearPendingConfirmation(conversationId) {
  if (conversationId === null || conversationId === undefined) {
    return;
  }
  await postJson('/api/confirmations/clear', {
    conversation_id: String(conversationId)
  });
}

export async function syncPendingConfirmations(conversationIds) {
  const ids = Array.isArray(conversationIds)
    ? conversationIds.filter((id) => id !== null && id !== undefined).map((id) => String(id))
    : [];
  await postJson('/api/confirmations/sync', {
    conversation_ids: ids
  });
}
