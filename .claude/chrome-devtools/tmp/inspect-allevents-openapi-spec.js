/**
 * Interact with AllEvents portal "API definition" dropdown to download OpenAPI spec.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const downloads = {};
    const cdpSession = await page.createCDPSession();

    // Enable download interception
    await cdpSession.send('Browser.setDownloadBehavior', {
        behavior: 'allow',
        downloadPath: 'e:\\OJT\\Veent Apps Inc\\SCRAPING\\veent-event-scraper\\.claude\\chrome-devtools\\tmp',
    });

    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        const cd = resp.headers()['content-disposition'] || '';
        if (ct.includes('yaml') || cd.includes('yaml') || cd.includes('json') || url.includes('export')) {
            try {
                const body = await resp.text().catch(() => '');
                if (body.length > 50) downloads[url] = body.substring(0, 10000);
            } catch (_) {}
        }
    });

    console.log('Loading API detail page...');
    await page.goto('https://allevents.developer.azure-api.net/api-details#api=5506d19acfdd541258b896c1&operation=55072579cfdd541258b896c2', {
        waitUntil: 'networkidle2', timeout: 30000,
    });
    await new Promise(r => setTimeout(r, 3000));

    // Find the "API definition" dropdown (it's a <select> element)
    const selectEl = await page.$('select');
    if (selectEl) {
        const options = await page.evaluate(sel => {
            const s = document.querySelector('select');
            return s ? [...s.options].map(o => ({ value: o.value, text: o.text })) : [];
        });
        console.log('Dropdown options:', JSON.stringify(options));

        // Select "Open API 3 (JSON)" or similar
        const jsonOption = options.find(o => o.text.toLowerCase().includes('json') && o.text.toLowerCase().includes('open'));
        const yamlOption = options.find(o => o.text.toLowerCase().includes('yaml'));
        const target = jsonOption || yamlOption;

        if (target) {
            console.log('Selecting:', target.text, '=', target.value);
            await page.select('select', target.value);
            await new Promise(r => setTimeout(r, 2000));

            // Look for a download link that appeared
            const links = await page.evaluate(() =>
                [...document.querySelectorAll('a[href]')].map(a => ({ text: a.innerText.trim(), href: a.href }))
                    .filter(l => l.href.includes('export') || l.text.includes('Download') || l.text.includes('download'))
            );
            console.log('Download links after selection:', JSON.stringify(links));

            // Try clicking download link if found
            if (links.length > 0) {
                console.log('Navigating to:', links[0].href);
                const r = await page.goto(links[0].href, { waitUntil: 'networkidle0', timeout: 15000 }).catch(() => null);
                if (r) {
                    const content = await page.evaluate(() => document.body.innerText || document.body.textContent || '').catch(() => '');
                    console.log('\nSpec content:', content.substring(0, 5000));
                }
            }
        }
    } else {
        // Check for non-select dropdown
        const ddText = await page.evaluate(() => {
            const dd = document.querySelector('[class*="dropdown"]') || document.querySelector('[class*="Definition"]');
            return dd ? dd.outerHTML.substring(0, 500) : 'not found';
        });
        console.log('Dropdown element:', ddText);
    }

    if (Object.keys(downloads).length > 0) {
        console.log('\n=== Downloaded specs ===');
        Object.entries(downloads).forEach(([url, body]) => {
            console.log(`\n${url}:`);
            console.log(body.substring(0, 5000));
        });
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
