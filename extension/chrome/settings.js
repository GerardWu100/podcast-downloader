/**
 * Stored settings and the small amount of URL and HTTP work both pages need.
 *
 * Settings live in chrome.storage.local rather than chrome.storage.sync: this
 * can hold your actual web interface password, and sync would copy it to every
 * browser profile connected to the same synchronization account.
 */

export const DEFAULT_SETTINGS = {
  // Clean origin, such as "http://192.168.1.20:6847". Options saves it
  // normalized, so every caller can use it as is.
  serverUrl: "",
  // Both blank when the server has login off.
  username: "",
  password: "",
  // Desktop notification after a successful add, not only the badge.
  notifyOnSuccess: true,
};

// How long a request may take before it is reported as unanswered. Long
// enough for a slow home server, short enough that the badge does not sit on
// "..." while a stopped background worker swallows the result.
export const REQUEST_TIMEOUT_MS = 15000;
const APP_NAME = "podcast-downloader";

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
 * Turn a saved or typed server address into a URL for one API path.
 *
 * "192.168.1.20:6847" + "/api/add-url" -> "http://192.168.1.20:6847/api/add-url"
 */
export function buildEndpoint(serverUrl, path) {
  return new URL(path, normalizeServerUrl(serverUrl)).toString();
}

/**
 * Return a typed server address as a clean origin, such as "https://host:8000".
 *
 * Accepts what a person actually types: with or without a scheme, with a path
 * or trailing slash. Without a scheme, an address on this machine or the home
 * network (localhost, a private IP, a .local or .lan name) gets http, because
 * that is how such a server is normally reached; anything else gets https,
 * because a password sent over plain http across the internet is readable by
 * anything in between. Throws an Error with a readable message when the
 * address cannot be used.
 */
export function normalizeServerUrl(serverUrl) {
  const typed = (serverUrl || "").trim();
  if (!typed) {
    throw new Error("Enter the address you open the web page at.");
  }
  let withScheme = typed;
  if (!/^https?:\/\//i.test(typed)) {
    const host = typed.split(/[/:]/)[0];
    withScheme = `${isHomeNetworkHost(host) ? "http" : "https"}://${typed}`;
  }
  let parsed;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new Error(`"${typed}" is not a valid server address.`);
  }
  return parsed.origin;
}

/** Whether a host name is this machine or a home-network address. */
export function isHomeNetworkHost(host) {
  const name = host.toLowerCase();
  return (
    name === "localhost" ||
    name.endsWith(".local") ||
    name.endsWith(".lan") ||
    name.endsWith(".home.arpa") ||
    /^127\./.test(name) ||
    /^10\./.test(name) ||
    /^192\.168\./.test(name) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(name)
  );
}

/**
 * Build the Authorization header value for a username and password.
 *
 * HTTP Basic sends base64("name:password"). btoa cannot encode characters
 * outside Latin-1, so the text is turned into UTF-8 bytes first; without that
 * step an accented character in a password throws instead of signing in.
 */
export function basicAuthHeader(username, password) {
  const utf8Bytes = new TextEncoder().encode(`${username}:${password}`);
  let latin1 = "";
  for (const byte of utf8Bytes) {
    latin1 += String.fromCharCode(byte);
  }
  return `Basic ${btoa(latin1)}`;
}

/**
 * Return the host permission pattern the extension must hold to call a server.
 *
 * The browser grants permission per origin, so the options page asks for
 * exactly the server the user typed instead of every site they visit.
 */
export function originPattern(serverUrl) {
  return `${normalizeServerUrl(serverUrl)}/*`;
}

/**
 * Call the server's JSON API and describe the result for a person.
 *
 * Every way this can go wrong ends in a readable `problem` rather than an
 * exception, so the toolbar worker and the options page report failures the
 * same way.
 *
 * @param {object} settings Saved or typed settings: serverUrl, username, password.
 * @param {string} path API path, such as "/api/ping".
 * @param {object} [init] fetch options (method, body).
 * @returns {Promise<{ok: boolean, status: number, body: object, problem: string}>}
 *   `body` is the parsed JSON reply ({} when there is none). `problem` is
 *   empty on success, else a title and an explanation joined by ": ".
 */
export async function callApi(settings, path, init = {}) {
  const endpoint = buildEndpoint(settings.serverUrl, path);
  const pattern = originPattern(settings.serverUrl);
  if (!(await chrome.permissions.contains({ origins: [pattern] }))) {
    return failure(0, `No permission for ${pattern}: open the extension options and select Save.`);
  }

  const headers = { Accept: "application/json", ...(init.headers || {}) };
  // Send a password only when one is saved. With login off, the server needs
  // nothing, and leaving both fields blank is the normal setup.
  if (settings.username) {
    headers.Authorization = basicAuthHeader(settings.username, settings.password);
  }

  let response;
  try {
    response = await fetch(endpoint, {
      ...init,
      headers,
      // Never follow a redirect with a password attached, and a redirect means
      // something other than Podcast Downloader answered anyway.
      redirect: "manual",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    if (error?.name === "TimeoutError") {
      return failure(0, `Server did not answer: ${endpoint} took more than ${REQUEST_TIMEOUT_MS / 1000} seconds.`);
    }
    return failure(0, `Could not reach the server: is ${new URL(endpoint).origin} running, and is the address right?`);
  }

  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  if (response.type === "opaqueredirect" || !isJson) {
    return failure(
      response.status,
      `Not Podcast Downloader: ${new URL(endpoint).origin} answered with a web page, not the app. Check the address, or a proxy login in front of it.`,
    );
  }
  const body = await response.json().catch(() => ({}));

  if (response.status === 401) {
    return failure(401, "Sign-in rejected: this server has login on. Enter the username and password from its .env in the extension options.", body);
  }
  if (response.status === 429) {
    return failure(429, `Too many failed attempts: ${readableDetail(body) || "wait 15 minutes, then fix the password in the options."}`, body);
  }
  if (response.status === 503) {
    return failure(503, `Server login is locked: ${readableDetail(body) || "fix UI_USERNAME and UI_PASSWORD in its .env and restart it."}`, body);
  }
  if (!response.ok && response.status !== 409) {
    return failure(response.status, `Server replied ${response.status}: ${readableDetail(body) || "no details."}`, body);
  }
  return { ok: response.ok, status: response.status, body, problem: "" };
}

/**
 * Return the server's explanation as text.
 *
 * Most replies carry a string. A rejected request body (422) carries a list
 * of {msg, input, ...} objects instead; only the messages are shown, because
 * `input` repeats whatever was sent, which can be thousands of characters.
 */
export function readableDetail(body) {
  const detail = body?.message ?? body?.detail;
  if (detail === undefined || detail === null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg ?? JSON.stringify(item)).join("; ");
  }
  return JSON.stringify(detail);
}

/** Whether a /api/ping reply came from Podcast Downloader. */
export function isPodcastDownloader(body) {
  return body?.app === APP_NAME;
}

function failure(status, problem, body = {}) {
  return { ok: false, status, body, problem };
}
