/**
 * Read AllEvents developer portal API details:
 * - Full API paths from the /developer/apis JSON
 * - Endpoint operations for List Events by City + Events Search Global
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    // Capture the developer/apis JSON directly
    let apisJson = null;
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

    // Load APIs page to trigger the /developer/apis request
    await page.goto('https://allevents.developer.azure-api.net/apis', {
        waitUntil: 'networkidle2', timeout: 30000,
    });
    await new Promise(r => setTimeout(r, 2000));

    // Print full API listing JSON
    const apisData = networkData.find(d => d.url.includes('/developer/apis'));
    if (apisData) {
        console.log('=== Full API Listing ===');
        console.log(JSON.stringify(apisData.body, null, 2));
    }

    // Now navigate to each key API details page and capture operations
    const targetApis = [
        { name: 'List Events by City', hash: '#api=5506d19acfdd541258b896c1' },
        { name: 'Events Search Global', hash: '#api=55e6f4cbadecff1658d2910c' },
        { name: 'Event Details', hash: '#api=event-details' },
        { name: 'Events by Geo', hash: '#api=559d0f69cfdd5405cce5b5c2' },
        { name: 'Events by Organizer', hash: '#api=598ad474adecff12f8d890ed' },
        { name: 'Search Organizers', hash: '#api=598ad298adecff12f8d890eb' },
    ];

    for (const api of targetApis) {
        const capturedOps = [];
        const opsListener = async resp => {
            const url = resp.url();
            const ct = resp.headers()['content-type'] || '';
            if (url.includes('/developer/') && ct.includes('json')) {
                try {
                    const body = await resp.json().catch(() => null);
                    if (body) capturedOps.push({ url, body });
                } catch (_) {}
            }
        };
        page.on('response', opsListener);

        await page.goto(`https://allevents.developer.azure-api.net/api-details${api.hash}`, {
            waitUntil: 'networkidle2', timeout: 20000,
        });
        await new Promise(r => setTimeout(r, 2000));

        const pageText = await page.evaluate(() => document.body.innerText.substring(0, 4000));
        console.log(`\n${'='.repeat(60)}`);
        console.log(`API: ${api.name}`);
        console.log(`${'='.repeat(60)}`);
        console.log(pageText);

        if (capturedOps.length > 0) {
            console.log('\nNetwork data:');
            capturedOps.forEach(d => console.log(d.url, '\n', JSON.stringify(d.body).substring(0, 800)));
        }

        page.off('response', opsListener);
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
