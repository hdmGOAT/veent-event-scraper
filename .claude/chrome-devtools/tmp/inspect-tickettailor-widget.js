/**
 * Inspect Ticket Tailor widget API by loading a known embed page.
 * The widget loads events for a box office from a separate API.
 * We capture those network calls here.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const apiCalls = [];
    const widgetCalls = [];

    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        // Capture widget/API calls from tickettailor domains
        if (url.includes('tickettailor') && !url.endsWith('.css')) {
            try {
                const body = await resp.text().catch(() => '');
                const entry = { url, status: resp.status(), contentType: ct, bodyPreview: body.substring(0, 800) };
                if (url.includes('widget') || url.includes('api') || url.includes('/js/')) {
                    widgetCalls.push(entry);
                } else if (ct.includes('json')) {
                    apiCalls.push(entry);
                }
            } catch (e) { /* ignore */ }
        }
    });

    // Load a page that embeds a Ticket Tailor box office widget
    // Ticket Tailor's own embed examples documentation uses their help center
    console.log('Loading Ticket Tailor widget script page...');

    // The widget script itself may reveal the API endpoint pattern
    // Let's try to load the widget JS directly
    const widgetResp = await page.goto('https://www.tickettailor.com/js/widgets/min/widget.js', {
        waitUntil: 'networkidle0',
        timeout: 20000,
    }).catch(e => ({ status: () => 0, url: () => 'error: ' + e.message }));

    const widgetContent = await page.content().catch(() => '');
    const widgetText = await page.evaluate(() => document.body.innerText || document.body.textContent || '').catch(() => '');

    console.log('Widget JS status:', widgetResp ? widgetResp.status() : 'failed');
    console.log('Widget JS size:', widgetText.length);

    // Search widget JS for API endpoint patterns
    const apiPatterns = widgetText.match(/https?:\/\/[^"'\s]+tickettailor[^"'\s]*/g) || [];
    const endpointPatterns = widgetText.match(/\/api\/[^"'\s]*/g) || [];
    const fetchPatterns = widgetText.match(/fetch\([^)]+\)/g) || [];

    console.log('\nAPI URL patterns found in widget JS:');
    apiPatterns.slice(0, 20).forEach(p => console.log(' ', p));

    console.log('\nEndpoint patterns:');
    endpointPatterns.slice(0, 20).forEach(p => console.log(' ', p));

    console.log('\nFetch calls:');
    fetchPatterns.slice(0, 10).forEach(p => console.log(' ', p.substring(0, 200)));

    // Check the non-Cloudflare subdomain for widget API
    console.log('\n=== Testing widget API subdomain ===');
    await page.goto('about:blank');

    // Try common widget API patterns
    const candidates = [
        'https://widget.tickettailor.com/api/',
        'https://cdn.tickettailor.com/',
        'https://api.tickettailor.com/v1/discover',
    ];

    for (const url of candidates) {
        const r = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 10000 }).catch(() => null);
        const status = r ? r.status() : 0;
        const title = await page.title().catch(() => '');
        console.log(`${url}: status=${status}, title=${title}`);
    }

    console.log('\nWidget network calls:', JSON.stringify(widgetCalls, null, 2));
    console.log('\nAPI JSON calls:', JSON.stringify(apiCalls, null, 2));

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
