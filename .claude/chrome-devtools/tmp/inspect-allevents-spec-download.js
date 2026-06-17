/**
 * Click the OpenAPI download links on AllEvents portal API detail pages.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const downloads = {};
    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        if (ct.includes('json') && (url.includes('export') || url.includes('openapi') || url.includes('swagger'))) {
            try {
                const body = await resp.text().catch(() => '');
                if (body.startsWith('{') || body.startsWith('openapi')) {
                    downloads[url] = body.substring(0, 8000);
                }
            } catch (_) {}
        }
    });

    // Load the List Events by City detail page
    await page.goto('https://allevents.developer.azure-api.net/api-details#api=5506d19acfdd541258b896c1', {
        waitUntil: 'networkidle2', timeout: 30000,
    });
    await new Promise(r => setTimeout(r, 3000));

    // Find and print all download-related links
    const links = await page.evaluate(() =>
        [...document.querySelectorAll('a[href]')].map(a => ({ text: a.innerText.trim(), href: a.href }))
            .filter(l => l.text && (l.href.includes('export') || l.href.includes('openapi') || l.href.includes('swagger') || l.text.toLowerCase().includes('open api') || l.text.toLowerCase().includes('yaml') || l.text.toLowerCase().includes('json')))
    );
    console.log('Download links found:');
    links.forEach(l => console.log(`  [${l.text}] ${l.href}`));

    // Click the Open API 3 (JSON) link
    const jsonLink = links.find(l => l.text.includes('JSON') || l.text.includes('json'));
    if (jsonLink) {
        console.log('\nNavigating to:', jsonLink.href);
        await page.goto(jsonLink.href, { waitUntil: 'networkidle0', timeout: 20000 }).catch(() => {});
        const content = await page.evaluate(() => document.body.innerText || '').catch(() => '');
        console.log('\nOpenAPI content:', content.substring(0, 5000));
    }

    // Also check what network calls were made
    if (Object.keys(downloads).length > 0) {
        console.log('\nCaptured downloads:');
        Object.entries(downloads).forEach(([url, body]) => {
            console.log(`\n${url}:`);
            console.log(body.substring(0, 3000));
        });
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
