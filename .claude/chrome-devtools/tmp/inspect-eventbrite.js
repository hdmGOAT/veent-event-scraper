/**
 * Inspect Eventbrite listing page:
 *  1. Capture all XHR/fetch JSON API calls
 *  2. Check __NEXT_DATA__ content
 *  3. Extract event card DOM structure & CSS selectors
 *  4. Identify pagination mechanism
 */
import { getBrowser, getPage, closeBrowser, outputJSON } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

const TARGET_URL = 'https://www.eventbrite.com/d/philippines--manila/all-events/';

async function main() {
  const browser = await getBrowser({ headless: true });
  const page = await getPage(browser);

  // Intercept XHR/fetch requests
  const apiCalls = [];
  page.on('response', async (response) => {
    const url = response.url();
    const ct = response.headers()['content-type'] || '';
    const rt = response.request().resourceType();
    if ((rt === 'xhr' || rt === 'fetch') && ct.includes('json')) {
      try {
        const body = await response.json();
        apiCalls.push({
          url,
          status: response.status(),
          bodyPreview: JSON.stringify(body).slice(0, 800),
        });
      } catch (_) {
        apiCalls.push({ url, status: response.status(), bodyPreview: '(parse error)' });
      }
    }
  });

  await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 45000 });

  // 1. __NEXT_DATA__
  const nextData = await page.evaluate(() => {
    const el = document.getElementById('__NEXT_DATA__');
    if (!el) return { found: false };
    try {
      const data = JSON.parse(el.textContent);
      const pp = (data.props || {}).pageProps || {};
      return {
        found: true,
        topKeys: Object.keys(data),
        ppKeys: Object.keys(pp),
        snippet: JSON.stringify(pp).slice(0, 5000),
      };
    } catch (e) {
      return { found: true, parseError: e.message };
    }
  });

  // 2. Event card structure — find the first 3 event cards
  const cardStructure = await page.evaluate(() => {
    // Try common Eventbrite card selectors
    const selectors = [
      '[data-testid="event-card"]',
      '.discover-search-desktop-card',
      '.search-event-card-wrapper',
      '[class*="EventCard"]',
      '[class*="event-card"]',
      'article[data-event-id]',
      '.eds-event-card',
      '[data-event]',
      'article',
    ];

    for (const sel of selectors) {
      const cards = document.querySelectorAll(sel);
      if (cards.length > 0) {
        const card = cards[0];
        return {
          selector: sel,
          count: cards.length,
          outerHTML: card.outerHTML.slice(0, 3000),
          // Extract fields from first few cards
          samples: Array.from(cards).slice(0, 3).map(c => {
            const link = c.querySelector('a');
            const heading = c.querySelector('h1,h2,h3,h4,h5,[class*="title"],[class*="name"]');
            const time = c.querySelector('time,[class*="date"],[class*="time"]');
            const img = c.querySelector('img');
            const price = c.querySelector('[class*="price"],[class*="Price"]');
            const venue = c.querySelector('[class*="venue"],[class*="location"],[class*="Location"]');
            const org = c.querySelector('[class*="organizer"],[class*="Organizer"]');
            return {
              href: link ? link.href : null,
              title: heading ? heading.textContent.trim().slice(0, 100) : null,
              time: time ? (time.getAttribute('datetime') || time.textContent.trim().slice(0, 80)) : null,
              imgSrc: img ? img.src : null,
              price: price ? price.textContent.trim().slice(0, 50) : null,
              venue: venue ? venue.textContent.trim().slice(0, 80) : null,
              organizer: org ? org.textContent.trim().slice(0, 80) : null,
            };
          }),
        };
      }
    }
    return { selector: null, count: 0, tried: selectors };
  });

  // 3. Pagination
  const pagination = await page.evaluate(() => {
    const nextBtn = document.querySelector('[aria-label*="next" i],[aria-label*="Next"],[data-testid*="next"],[class*="pagination"] a,[class*="Pagination"] a');
    const pageLinks = document.querySelectorAll('[class*="pagination"] a, [class*="Pagination"] a');
    return {
      nextButton: nextBtn ? { text: nextBtn.textContent.trim(), href: nextBtn.href } : null,
      pageLinks: Array.from(pageLinks).map(a => ({ text: a.textContent.trim(), href: a.href })).slice(0, 5),
      currentUrl: location.href,
    };
  });

  // 4. Look for any embedded JSON script tags (besides __NEXT_DATA__)
  const embeddedScripts = await page.evaluate(() => {
    const scripts = Array.from(document.querySelectorAll('script[type="application/json"], script[type="application/ld+json"]'));
    return scripts.map(s => ({
      type: s.type,
      id: s.id,
      preview: s.textContent.slice(0, 500),
    }));
  });

  outputJSON({
    nextData,
    cardStructure,
    pagination,
    embeddedScripts: embeddedScripts.slice(0, 5),
    apiCalls: apiCalls.slice(0, 20),
  });

  await closeBrowser();
}

main().catch(e => { console.error(e); process.exit(1); });
