/**
 * Settings page: server address and the same sign-in you use on the web page.
 *
 * Saving also asks Chrome for permission to talk to that one server. The
 * manifest requests no host permissions up front, so the extension can only
 * reach the address you type here.
 */

import {
  basicAuthHeader,
  buildEndpoint,
  originPattern,
  readSettings,
  writeSettings,
} from "./settings.js";

const serverUrlInput = document.getElementById("server-url");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const statusLine = document.getElementById("status");

document.getElementById("save").addEventListener("click", save);
document.getElementById("test").addEventListener("click", testConnection);

const settings = await readSettings();
serverUrlInput.value = settings.serverUrl;
usernameInput.value = settings.username;
passwordInput.value = settings.password;

async function save() {
  let pattern;
  try {
    pattern = originPattern(serverUrlInput.value);
  } catch (error) {
    show(error.message, false);
    return;
  }

  // Browsers only show this prompt in response to a click, which is why the
  // permission is requested here rather than on the first download attempt.
  const granted = await chrome.permissions.request({ origins: [pattern] });
  if (!granted) {
    show(`The browser did not grant access to ${pattern}. Nothing was saved.`, false);
    return;
  }

  const previousSettings = await readSettings();
  await writeSettings({
    serverUrl: serverUrlInput.value.trim(),
    username: usernameInput.value.trim(),
    password: passwordInput.value,
  });

  // Changing servers must not leave access to every previously configured
  // origin behind. Remove only after the new settings are safely stored, so a
  // refused permission prompt cannot break the working configuration.
  if (previousSettings.serverUrl) {
    try {
      const previousPattern = originPattern(previousSettings.serverUrl);
      if (previousPattern !== pattern) {
        await chrome.permissions.remove({ origins: [previousPattern] });
      }
    } catch {
      // An invalid old value grants no useful origin and should not block Save.
    }
  }
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

  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  if (!username || !password) {
    show("Enter your username and password first.", false);
    return;
  }

  let response;
  try {
    response = await fetch(endpoint, {
      headers: { Authorization: basicAuthHeader(username, password) },
    });
  } catch {
    show(`Could not reach ${endpoint}. Press Save first to grant access, then try again.`, false);
    return;
  }

  if (response.status === 401) {
    show("The server did not accept that username and password.", false);
    return;
  }
  if (response.status === 429) {
    show("Too many failed attempts from this machine. Wait a few minutes and try again.", false);
    return;
  }
  if (response.status === 503) {
    show("The server has no accounts configured. Set UI_USERNAME and UI_PASSWORD in its .env and restart it.", false);
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
