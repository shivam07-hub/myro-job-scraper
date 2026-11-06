(async () => {
  // Runs inside the Firecrawl render of BNP Paribas' India job list (see bnp_paribas.py).
  // Reads every list page and every offer page at a steady pace, as a reader pressing
  // "See more job offers" would, and writes the offers into <pre id="myro-bnp">.
  // The <pre> is written only when every list page loaded, so a partial list fails
  // the render's next wait instead of being cached for a week.
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const parse = (html) => new DOMParser().parseFromString(html, "text/html");
  const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const cardsOf = (doc) =>
    [...doc.querySelectorAll('a.card-link[href*="/careers/job-offer/"]')].map((a) => ({
      href: a.getAttribute("href"),
      title: text(a.querySelector("h3")),
      location: text(a.querySelector(".offer-location")),
    }));

  async function get(url) {
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const response = await fetch(url, { credentials: "same-origin" });
        if (response.ok) return await response.text();
      } catch (_) {
        // retried below
      }
      await sleep(1500 * attempt);
    }
    return null;
  }

  async function pool(items, workers, task) {
    let next = 0;
    await Promise.all(
      Array.from({ length: workers }, async () => {
        while (next < items.length) {
          await task(items[next++]);
          await sleep(150);
        }
      })
    );
  }

  let lastPage = 1;
  document.querySelectorAll(".pagination a[data-to]").forEach((a) => {
    lastPage = Math.max(lastPage, Number(a.dataset.to) || 1);
  });
  const base = location.origin + location.pathname;
  const cards = cardsOf(document);
  let missingPages = 0;
  const pageUrls = Array.from({ length: lastPage - 1 }, (_, k) => `${base}?page=${k + 2}`);
  await pool(pageUrls, 3, async (url) => {
    const html = await get(url);
    if (html === null) missingPages++;
    else cards.push(...cardsOf(parse(html)));
  });
  if (missingPages) return;

  const seen = new Set();
  const offers = cards.filter((card) => !seen.has(card.href) && seen.add(card.href));
  await pool(offers, 4, async (offer) => {
    const html = await get(offer.href);
    if (html === null) return;
    const avature = html.match(/JobDetails\?jobId=(\d+)/);
    const posted = html.match(/"datePosted":\s*"([^"]+)"/);
    const ref = html.match(/"identifier"[\s\S]*?"value":\s*"([^"]+)"/);
    offer.jobId = avature ? avature[1] : null;
    offer.datePosted = posted ? posted[1] : null;
    offer.ref = ref ? ref[1] : null;
  });

  const result = document.createElement("pre");
  result.id = "myro-bnp";
  result.textContent = JSON.stringify({ lastPage, offers });
  document.body.appendChild(result);
})()
