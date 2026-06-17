/**
 * Visit allevents.in Manila page with real browser to capture XHR calls.
 * Cloudflare may pass headless Chrome — if so, we capture the internal API format.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const xhrCalls = [];
    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        if (ct.includes('json') && url.includes('allevents')) {
            try {
                const body = await resp.text().catch(() => '');
                if (body.length > 20) {
                    xhrCalls.push({ url, status: resp.status(), bodyPreview: body.substring(0, 2000) });
                }
            } catch (_) {}
        }
    });

    // Try Manila events listing — Cloudflare JS challenge may pass with real Chrome
    console.log('Navigating to allevents.in/manila...');
    const resp = await page.goto('https://allevents.in/manila/', {
        waitUntil: 'networkidle2', timeout: 40000,
    }).catch(e => null);

    await new Promise(r => setTimeout(r, 4000));

    const pageInfo = await page.evaluate(() => ({
        title: document.title,
        url: location.href,
        bodyPreview: document.body.innerText.substring(0, 1000),
    }));

    console.log('Title:', pageInfo.title);
    console.log('URL:', pageInfo.url);
    console.log('Body preview:', pageInfo.bodyPreview);

    if (xhrCalls.length > 0) {
        console.log('\n=== XHR/JSON calls captured ===');
        xhrCalls.forEach(c => {
            console.log(`\n[${c.status}] ${c.url}`);
            console.log(c.bodyPreview);
        });
    } else {
        console.log('\nNo JSON XHR calls captured (Cloudflare blocked or page loaded without API calls)');
    }

    // Also try the /api/ path directly with a browser context (has cookies from the main page)
    if (pageInfo.title !== 'Just a moment...') {
        console.log('\n=== Trying /api/ with browser cookies ===');
        const apiResp = await page.goto('https://allevents.in/api/v3/events?city=Manila&country=PH', {
            waitUntil: 'domcontentloaded', timeout: 15000,
        }).catch(() => null);
        if (apiResp) {
            const apiContent = await page.evaluate(() => document.body.innerText).catch(() => '');
            console.log('API response:', apiContent.substring(0, 2000));
        }
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
