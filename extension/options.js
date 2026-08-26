/**
 * Settings page: server address, API token, and the immediate-download choice.
 *
 * Saving also asks Chrome for permission to talk to that one server. The
 * manifest requests no host permissions up front, so the extension can only
 * reach the address you type here.
 */

import {
  buildEndpoint,
  originPattern,
  readSettings,
  writeSettings,
} from "./settings.js";

const serverUrlInput = document.getElementById("server-url");
const apiTokenInput = document.getElementById("api-token");
const downloadImmediatelyInput = document.getElementById("download-immediately");
const statusLine = document.getElementById("status");

document.getElementById("save").addEventListener("click", save);
document.getElementById("test").addEventListener("click", testConnection);

const settings = await readSettings();
serverUrlInput.value = settings.serverUrl;
apiTokenInput.value = settings.apiToken;
downloadImmediatelyInput.checked = settings.downloadImmediately;

async function save() {
  let pattern;
  try {
    pattern = originPattern(serverUrlInput.value);
  } catch (error) {
    show(error.message, false);
    return;
  }

  // Chrome only shows this prompt in response to a click, which is why the
  // permission is requested here rather than on the first download attempt.
  const granted = await chrome.permissions.request({ origins: [pattern] });
  if (!granted) {
    show(`Chrome did not grant access to ${pattern}. Nothing was saved.`, false);
    return;
  }

  await writeSettings({
    serverUrl: serverUrlInput.value.trim(),
    apiToken: apiTokenInput.value.trim(),
    downloadImmediately: downloadImmediatelyInput.checked,
  });
  show("Saved.", true);
}

async function testConnection() {
  let endpoint;
  try {
    endpoint = buildEndpoint(serverUrlInput.value, "/api/ping");
  } catch (error) {
    show(error.message, false);
    return;
  }

  const token = apiTokenInput.value.trim();
  if (!token) {
    show("Enter the API token first.", false);
    return;
  }

  let response;
  try {
    response = await fetch(endpoint, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    show(`Could not reach ${endpoint}. Press Save first to grant access, then try again.`, false);
    return;
  }

  if (response.status === 401) {
    show("The server rejected this token.", false);
    return;
  }
  if (response.status === 503) {
    show("The server has no PODCAST_API_TOKEN set. Add one to .env and restart it.", false);
    return;
  }
  if (!response.ok) {
    show(`The server replied ${response.status}.`, false);
    return;
  }
  show("Connected.", true);
}

function show(message, succeeded) {
  statusLine.textContent = message;
  statusLine.className = succeeded ? "ok" : "error";
}
