/**
 * Background worker: turns a click, a menu choice, or a shortcut into one
 * POST /api/add-url call against the user's Podcast Downloader. Chrome runs it
 * as a service worker; Firefox runs it as a non-persistent background page.
 *
 * The server authenticates this extension with the web account stored in the
 * extension options (or nothing, when the server has login off), not the web
 * interface's login session. That session cookie is HttpOnly, so no script can
 * read it, and SameSite=lax, so the browser would not send it on a cross-site
 * POST.
 *
 * The extension reads a page's address only at the moment you ask it to. That
 * is what the activeTab permission means: clicking the toolbar icon, choosing
 * the context menu item, or pressing the shortcut grants access to that one
 * tab, and nothing else. It never sees your browsing otherwise.
 *
 * Firefox for Android has no context menus, keyboard commands, or desktop
 * notifications, so every use of those APIs is guarded; there the toolbar
 * button and its badge still work.
 */

import { callApi, readSettings } from "./settings.js";

const MENU_ITEM_PAGE = "add-page";
const MENU_ITEM_LINK = "add-link";
// Where the right-click menu items are offered. This is only about keeping the
// menu out of the way on unrelated sites: the server accepts any http or https
// link, because yt-dlp handles far more sites than these. Chrome match
// patterns treat "*.youtube.com" as covering youtube.com itself along with
// m., music., and any other subdomain.
const MENU_SITE_PATTERNS = [
  "*://*.youtube.com/*",
  "*://youtu.be/*",
  "*://*.rumble.com/*",
];
const BADGE_CLEAR_DELAY_MS = 6000;
const BADGE_COLORS = { pending: "#6b7280", success: "#1a7f37", failure: "#b42318" };
const DEFAULT_TITLE = "Add this page to the podcast queue";
// Outcomes the server reports for a URL it accepted or knowingly skipped.
// Anything else is treated as a failure worth a notification.
const EXPECTED_OUTCOMES = new Set(["added", "duplicate", "downloaded"]);
// Badge text per outcome: a new item, or one that was already handled.
const OUTCOME_BADGES = { added: "OK", duplicate: "=", downloaded: "=" };

// One pending badge-clear timer per tab (tab id, or "all" for no tab). A new
// submission cancels the old timer, so a quick second click cannot have its
// result wiped by the first click's timer.
const badgeClearTimers = new Map();

chrome.runtime.onInstalled.addListener(() => {
  if (!chrome.contextMenus) return;
  chrome.contextMenus.removeAll(() => {
    // documentUrlPatterns filters on the page (or frame) you are looking at,
    // so this item appears only on YouTube or Rumble, including a player
    // embedded in another site.
    chrome.contextMenus.create({
      id: MENU_ITEM_PAGE,
      title: "Add this video to the podcast queue",
      contexts: ["page", "video", "audio", "frame"],
      documentUrlPatterns: MENU_SITE_PATTERNS,
    });
    // targetUrlPatterns filters on the link itself, not the page holding it.
    // A YouTube link still offers this item when you find it on a forum, a
    // blog, or anywhere else.
    chrome.contextMenus.create({
      id: MENU_ITEM_LINK,
      title: "Add this link to the podcast queue",
      contexts: ["link"],
      targetUrlPatterns: MENU_SITE_PATTERNS,
    });
  });
});

chrome.action.onClicked.addListener((tab) => {
  submitUrl(tab?.url, tab?.id);
});

chrome.commands?.onCommand.addListener((command, tab) => {
  if (command !== "add-current-tab") return;
  // Chrome passes the active tab with the command, and the activeTab
  // permission makes its URL readable. Querying for the tab instead would
  // return an object with the URL stripped out.
  submitUrl(tab?.url, tab?.id);
});

chrome.contextMenus?.onClicked.addListener((info, tab) => {
  // In an embedded player, the frame holds the video's address; the page is
  // the blog or forum around it, which is not a media URL.
  const url =
    info.menuItemId === MENU_ITEM_LINK ? info.linkUrl : info.frameUrl || info.pageUrl;
  submitUrl(url, tab?.id);
});

/**
 * Send one URL to the queue and report the result on the toolbar icon.
 *
 * Every failure path ends in a notification, because the toolbar badge alone
 * cannot say why something did not work. The button's tooltip also keeps the
 * last result's message for that tab.
 */
async function submitUrl(url, tabId) {
  await setBadge("...", BADGE_COLORS.pending, tabId);

  if (!url || !/^https?:/i.test(url)) {
    await report(false, "Nothing to add", "This tab is not a web page with a video.", tabId);
    return;
  }

  const settings = await readSettings();
  if (!settings.serverUrl) {
    // A first click on an extension nobody has set up: opening the settings
    // page is the whole instruction.
    await setBadge("!", BADGE_COLORS.failure, tabId);
    scheduleBadgeClear(tabId);
    chrome.runtime.openOptionsPage();
    return;
  }

  // Only the URL. The server decides what happens next, using the same queue
  // rules the web page follows: a direct video starts right away, a channel
  // waits for the next scheduled run.
  const result = await callApi(settings, "/api/add-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (result.problem) {
    const [title, ...rest] = result.problem.split(": ");
    await report(false, title, rest.join(": "), tabId);
    return;
  }

  const { outcome, message, immediate } = result.body;
  if (!EXPECTED_OUTCOMES.has(outcome)) {
    await report(false, "Not added", message || `Server replied ${result.status}.`, tabId);
    return;
  }

  // "duplicate" and "downloaded" are successes from the user's point of view:
  // the episode is already handled, so nothing is wrong and nothing is lost.
  const detail =
    outcome === "added"
      ? immediate
        ? "Added. Downloading now."
        : "Added. It downloads on the next scheduled run."
      : message;
  await setBadge(OUTCOME_BADGES[outcome], BADGE_COLORS.success, tabId);
  await setTitle(`Podcast Downloader: ${detail}`, tabId);
  scheduleBadgeClear(tabId);
  if (settings.notifyOnSuccess) {
    notify(detail, url);
  }
}

/** Show a failure on the badge, the tooltip, and in a desktop notification. */
async function report(succeeded, title, message, tabId) {
  await setBadge(succeeded ? "OK" : "!", succeeded ? BADGE_COLORS.success : BADGE_COLORS.failure, tabId);
  await setTitle(`Podcast Downloader: ${title}. ${message}`, tabId);
  scheduleBadgeClear(tabId);
  notify(title, message);
}

function notify(title, message) {
  // Absent on Firefox for Android; the badge and tooltip still say it.
  chrome.notifications?.create({
    type: "basic",
    iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
    title: `Podcast Downloader: ${title}`,
    message: String(message),
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

async function setTitle(title, tabId) {
  const target = tabId === undefined ? {} : { tabId };
  try {
    await chrome.action.setTitle({ title, ...target });
  } catch {
    // Same as the badge: a closed tab is not an error.
  }
}

/**
 * Clear the badge after a few seconds, keeping one timer per tab.
 *
 * Chrome can stop this service worker before the timer fires, which leaves the
 * badge on screen. That is harmless: the next submission overwrites it.
 */
function scheduleBadgeClear(tabId) {
  const key = tabId ?? "all";
  clearTimeout(badgeClearTimers.get(key));
  badgeClearTimers.set(
    key,
    setTimeout(() => {
      badgeClearTimers.delete(key);
      setBadge("", BADGE_COLORS.success, tabId);
      setTitle(DEFAULT_TITLE, tabId);
    }, BADGE_CLEAR_DELAY_MS),
  );
}
