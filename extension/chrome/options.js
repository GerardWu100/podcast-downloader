/**
 * Settings page: server address, an optional sign-in, and success notifications.
 *
 * Save asks the browser for permission to talk to that one server (the
 * manifest requests no host permissions up front), stores the address as a
 * clean origin, and then tests the connection, so a wrong address or password
 * shows up here instead of later as a failed submission.
 */

import {
  callApi,
  isPodcastDownloader,
  normalizeServerUrl,
  originPattern,
  readSettings,
  writeSettings,
} from "./settings.js";

const form = document.getElementById("settings-form");
const serverUrlInput = document.getElementById("server-url");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const notifyInput = document.getElementById("notify-on-success");
const statusLine = document.getElementById("status");
const shortcutText = document.getElementById("shortcut-text");
const shortcutButton = document.getElementById("shortcut-settings");

form.addEventListener("submit", (event) => {
  event.preventDefault();
  save();
});
shortcutButton.addEventListener("click", openShortcutSettings);

const settings = await readSettings();
serverUrlInput.value = settings.serverUrl;
usernameInput.value = settings.username;
passwordInput.value = settings.password;
notifyInput.checked = settings.notifyOnSuccess;
showShortcut();

// Clicking the toolbar icon before anything is saved opens this page, so say
// what to do rather than leaving a blank form and no explanation.
if (!settings.serverUrl) {
  show("Enter the address you open the web page at, then select Save and test.", true);
  serverUrlInput.focus();
}

async function save() {
  let origin;
  let pattern;
  try {
    origin = normalizeServerUrl(serverUrlInput.value);
    pattern = originPattern(origin);
  } catch (error) {
    show(error.message, false);
    return;
  }
  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  if (Boolean(username) !== Boolean(password)) {
    show("Fill in both username and password, or leave both blank if the server has no login.", false);
    return;
  }

  // Firefox only shows this prompt while the click still counts as the user's
  // action, so it must be the first thing awaited after the click.
  const granted = await chrome.permissions.request({ origins: [pattern] });
  if (!granted) {
    show(`The browser did not grant access to ${origin}. Nothing was saved.`, false);
    return;
  }

  const previousSettings = await readSettings();
  const newSettings = {
    serverUrl: origin,
    username,
    password,
    notifyOnSuccess: notifyInput.checked,
  };
  await writeSettings(newSettings);
  serverUrlInput.value = origin;

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

  show(`Saved. Testing ${origin}…`, true);
  await testConnection(newSettings);
}

async function testConnection(savedSettings) {
  const result = await callApi(savedSettings, "/api/ping");
  if (result.problem) {
    show(`Saved, but the test failed. ${result.problem}`, false);
    return;
  }
  if (!isPodcastDownloader(result.body)) {
    show(`Saved, but ${savedSettings.serverUrl} is not Podcast Downloader. Check the address.`, false);
    return;
  }
  const version = result.body.version ? ` ${result.body.version}` : "";
  const login = result.body.login_required
    ? `signed in as ${savedSettings.username}`
    : savedSettings.username
      ? "login is off on the server, so the username and password are not needed"
      : "no login needed";
  show(`Connected to Podcast Downloader${version}; ${login}.`, true);
}

async function showShortcut() {
  if (!chrome.commands) {
    shortcutText.textContent = "This browser has no keyboard shortcuts for add-ons.";
    shortcutButton.hidden = true;
    return;
  }
  const commands = await chrome.commands.getAll();
  const addCommand = commands.find((command) => command.name === "add-current-tab");
  // The browser drops the suggested shortcut silently when it clashes with
  // another one, so show what was actually assigned.
  shortcutText.textContent = addCommand?.shortcut
    ? `${addCommand.shortcut} adds the current page.`
    : "No shortcut is assigned, usually because another add-on already uses Alt+Shift+D.";
}

function openShortcutSettings() {
  // Firefox 137+ opens its shortcut page directly; Chrome's lives at a
  // chrome:// address that only the tabs API may open.
  if (chrome.commands?.openShortcutSettings) {
    chrome.commands.openShortcutSettings();
  } else {
    chrome.tabs.create({ url: "chrome://extensions/shortcuts" });
  }
}

function show(message, succeeded) {
  statusLine.textContent = message;
  statusLine.className = succeeded ? "ok" : "error";
}
