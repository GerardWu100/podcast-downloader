/**
 * Stored settings and the small amount of URL work both pages need.
 *
 * Settings live in chrome.storage.local rather than chrome.storage.sync: the
 * API token is a password for your server, and sync would copy it to every
 * Chrome profile signed in to the same Google account.
 */

export const SETTINGS_KEYS = {
  serverUrl: "serverUrl",
  apiToken: "apiToken",
  downloadImmediately: "downloadImmediately",
};

export const DEFAULT_SETTINGS = {
  serverUrl: "",
  apiToken: "",
  downloadImmediately: false,
};

/** Read the saved settings, filling in defaults for anything never set. */
export async function readSettings() {
  const stored = await chrome.storage.local.get(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS, ...stored };
}

/** Save settings. Pass only the keys you are changing. */
export async function writeSettings(changes) {
  await chrome.storage.local.set(changes);
}

/**
 * Turn a typed server address into a URL for one API path.
 *
 * Accepts what a person actually types: with or without a scheme, with or
 * without a trailing slash. Throws an Error with a readable message when the
 * address cannot be used.
 *
 * "podcast.example.com" + "/api/add-url"
 *   -> "https://podcast.example.com/api/add-url"
 */
export function buildEndpoint(serverUrl, path) {
  const base = normalizeServerUrl(serverUrl);
  return new URL(path, base).toString();
}

/**
 * Return the server address as a clean origin, e.g. "https://host:8000".
 *
 * A bare host gets https, because a token sent over plain http is readable by
 * anything on the network in between. Type "http://" yourself if the server is
 * on your own machine.
 */
export function normalizeServerUrl(serverUrl) {
  const typed = (serverUrl || "").trim();
  if (!typed) {
    throw new Error("No server address saved. Open the extension options.");
  }
  const withScheme = /^https?:\/\//i.test(typed) ? typed : `https://${typed}`;
  let parsed;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new Error(`"${typed}" is not a valid server address.`);
  }
  return parsed.origin;
}

/**
 * Return the host permission pattern the extension must hold to call a server.
 *
 * Chrome grants permission per origin, so the options page asks for exactly the
 * server the user typed instead of every site they visit.
 */
export function originPattern(serverUrl) {
  return `${normalizeServerUrl(serverUrl)}/*`;
}
