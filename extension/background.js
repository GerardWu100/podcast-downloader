/**
 * Service worker: turns a click, a menu choice, or a shortcut into one
 * POST /api/add-url call against the user's Podcast Downloader.
 *
 * The server authenticates this extension with a bearer token, not the web
 * interface's login session. That session cookie is HttpOnly, so no script can
 * read it, and SameSite=lax, so the browser would not send it on a cross-site
 * POST. The token is stored in the extension options.
 *
 * The extension reads a page's address only at the moment you ask it to. That
 * is what the activeTab permission means: clicking the toolbar icon, choosing
 * the context menu item, or pressing the shortcut grants access to that one
 * tab, and nothing else. It never sees your browsing otherwise.
 */

import { basicAuthHeader, buildEndpoint, readSettings } from "./settings.js";

const MENU_ITEM_PAGE = "add-page";
const MENU_ITEM_LINK = "add-link";
const BADGE_CLEAR_DELAY_MS = 4000;
const BADGE_COLORS = { success: "#1a7f37", failure: "#b42318" };
// Outcomes the server reports for a URL it accepted or knowingly skipped.
// Anything else is treated as a failure worth a notification.
const EXPECTED_OUTCOMES = new Set(["added", "duplicate", "downloaded"]);

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ITEM_PAGE,
      title: "Add this page to the podcast queue",
      contexts: ["page", "video", "audio"],
    });
    chrome.contextMenus.create({
      id: MENU_ITEM_LINK,
      title: "Add this link to the podcast queue",
      contexts: ["link"],
    });
  });
});

chrome.action.onClicked.addListener((tab) => {
  submitUrl(tab?.url, tab?.id);
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command !== "add-current-tab") return;
  // Chrome passes the active tab with the command, and the activeTab
  // permission makes its URL readable. Querying for the tab instead would
  // return an object with the URL stripped out.
  submitUrl(tab?.url, tab?.id);
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.menuItemId === MENU_ITEM_LINK ? info.linkUrl : info.pageUrl;
  submitUrl(url, tab?.id);
});

/**
 * Send one URL to the queue and report the result on the toolbar icon.
 *
 * Every failure path ends in a notification, because the toolbar badge alone
 * cannot say why something did not work.
 */
async function submitUrl(url, tabId) {
  await setBadge("...", BADGE_COLORS.success, tabId);

  if (!url) {
    await report(false, "No page URL", "Chrome did not provide a URL for this tab.", tabId);
    return;
  }

  let settings;
  let endpoint;
  try {
    settings = await readSettings();
    endpoint = buildEndpoint(settings.serverUrl, "/api/add-url");
  } catch (error) {
    await report(false, "Not set up yet", error.message, tabId);
    return;
  }

  if (!settings.username || !settings.password) {
    await report(false, "Not signed in", "Open the extension options and enter your username and password.", tabId);
    return;
  }

  let response;
  let body;
  try {
    response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: basicAuthHeader(settings.username, settings.password),
      },
      body: JSON.stringify({
        url,
        skip_age_check: settings.downloadImmediately,
      }),
    });
    body = await response.json().catch(() => ({}));
  } catch (error) {
    // A network-level failure here usually means the server is unreachable or
    // the extension was never granted permission for that origin.
    await report(
      false,
      "Could not reach the server",
      `${endpoint} did not respond. Check the address and, in the options, press Save to grant access.`,
      tabId,
    );
    return;
  }

  if (response.status === 401) {
    await report(false, "Sign-in rejected", "The server did not accept that username and password.", tabId);
    return;
  }
  if (response.status === 429) {
    // The server bans an address after repeated failures, the same rule the
    // login page applies. Usually it means a saved password is out of date.
    await report(false, "Too many failed attempts", body.detail || "Wait a few minutes, then check your password in the options.", tabId);
    return;
  }
  if (response.status === 503) {
    await report(false, "Server has no accounts", body.detail || "Set UI_USERNAME and UI_PASSWORD in .env and restart.", tabId);
    return;
  }
  if (!EXPECTED_OUTCOMES.has(body.outcome)) {
    await report(false, "Not added", body.message || body.detail || `Server replied ${response.status}.`, tabId);
    return;
  }

  // "duplicate" and "downloaded" are successes from the user's point of view:
  // the episode is already handled, so nothing is wrong and nothing is lost.
  await setBadge(body.outcome === "added" ? "OK" : "=", BADGE_COLORS.success, tabId);
  scheduleBadgeClear(tabId);
}

/** Show a failure on the badge and in a desktop notification. */
async function report(succeeded, title, message, tabId) {
  await setBadge(succeeded ? "OK" : "!", succeeded ? BADGE_COLORS.success : BADGE_COLORS.failure, tabId);
  scheduleBadgeClear(tabId);
  chrome.notifications.create({
    type: "basic",
    iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
    title: `Podcast Downloader: ${title}`,
    message,
  });
}

async function setBadge(text, color, tabId) {
  const target = tabId === undefined ? {} : { tabId };
  try {
    await chrome.action.setBadgeBackgroundColor({ color, ...target });
    await chrome.action.setBadgeText({ text, ...target });
  } catch {
    // The tab can close between the request and the reply; a missing badge is
    // not worth failing the submission over.
  }
}

/**
 * Clear the badge after a few seconds.
 *
 * Chrome can stop this service worker before the timer fires, which leaves the
 * badge on screen. That is harmless: the next submission overwrites it.
 */
function scheduleBadgeClear(tabId) {
  setTimeout(() => setBadge("", BADGE_COLORS.success, tabId), BADGE_CLEAR_DELAY_MS);
}
