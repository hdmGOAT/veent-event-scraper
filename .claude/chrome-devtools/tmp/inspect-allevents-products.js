/**
 * Read AllEvents developer portal Products page for subscription/pricing info.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const networkData = [];
    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        if (url.includes('/developer/') && ct.includes('json')) {
            try {
                const body = await resp.json().catch(() => null);
                if (body) networkData.push({ url, body });
            } catch (_) {}
        }
    });

    await page.goto('https://allevents.developer.azure-api.net/products', {
        waitUntil: 'networkidle2', timeout: 30000,
    });
    await new Promise(r => setTimeout(r, 2000));

    const text = await page.evaluate(() => document.body.innerText.substring(0, 5000));
    console.log('=== Products page ===');
    console.log(text);

    if (networkData.length > 0) {
        console.log('\n=== Products JSON ===');
        networkData.forEach(d => console.log(d.url, '\n', JSON.stringify(d.body, null, 2).substring(0, 2000)));
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
