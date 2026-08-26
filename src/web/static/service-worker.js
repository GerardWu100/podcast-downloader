// Minimal service worker for the installed phone app.
//
// It caches nothing. Every request goes to the network exactly as it would
// without a service worker. The file exists because browsers only offer to
// install a site as an app once a service worker with a fetch listener is
// registered, and because an installed app needs one to launch from the home
// screen. Deliberately not caching keeps the queue and activity pages live and
// avoids serving a stale UI after a deploy.

self.addEventListener("install", () => {
  // Replace an older worker immediately instead of waiting for every tab to
  // close, so a redeploy takes effect on the next page load.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // No respondWith call here, so the browser handles the request normally.
});
