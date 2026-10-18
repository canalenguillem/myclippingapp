const MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** El texto de las palabras viene del usuario: se escapa siempre antes de entrar en la composición. */
export const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => MAP[c]);
