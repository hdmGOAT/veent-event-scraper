/**
 * Download OpenAPI specs for key AllEvents APIs via the developer portal.
 * The portal exposes these without authentication.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const specs = {};
    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        if ((ct.includes('json') || ct.includes('yaml')) && url.includes('export')) {
            try {
                const body = await resp.text().catch(() => '');
                specs[url] = body.substring(0, 5000);
            } catch (_) {}
        }
    });

    // Try fetching the OpenAPI export URLs directly
    // Azure APIM export format: /developer/apis/{id}/export?format=openapi3&api-version=...
    const apiIds = {
        'list-events-by-city': '5506d19acfdd541258b896c1',
        'events-search-global': '55e6f4cbadecff1658d2910c',
        'event-details': 'event-details',
        'events-by-geo': '559d0f69cfdd5405cce5b5c2',
        'events-by-organizer': '598ad474adecff12f8d890ed',
        'search-organizers': '598ad298adecff12f8d890eb',
    };

    for (const [name, id] of Object.entries(apiIds)) {
        const exportUrl = `https://allevents.developer.azure-api.net/developer/apis/${id}/export?format=openapi3&api-version=2022-04-01-preview`;
        await page.goto(exportUrl, { waitUntil: 'networkidle0', timeout: 15000 }).catch(() => {});
        const content = await page.evaluate(() => document.body.innerText || '').catch(() => '');
        console.log(`\n${'='.repeat(60)}`);
        console.log(`OpenAPI: ${name}`);
        console.log(`${'='.repeat(60)}`);
        console.log(content.substring(0, 3000));
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
