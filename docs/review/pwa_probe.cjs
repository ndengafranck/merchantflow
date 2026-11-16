const { chromium } = require("playwright");
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext(); const p = await ctx.newPage();
  await p.goto("http://localhost:4173/login"); await p.waitForTimeout(1500);
  const cdp = await ctx.newCDPSession(p);
  const m = await cdp.send("Page.getAppManifest");
  console.log("manifest url:", m.url, "| parse errors:", JSON.stringify(m.errors));
  console.log("installability errors:", JSON.stringify((await cdp.send("Page.getInstallabilityErrors")).installabilityErrors));
  console.log("service worker registrations:", await p.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length));
  console.log("head:", await p.evaluate(() => [...document.head.querySelectorAll("meta,link")].map(e => e.outerHTML).join("\n      ")));
  await ctx.setOffline(true);
  const off = await p.reload().then(() => "LOADED").catch(e => "FAILED: " + e.message.split("\n")[0]);
  console.log("reload while offline:", off);
  await b.close();
})();
