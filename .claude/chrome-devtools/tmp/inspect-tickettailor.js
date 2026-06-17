/**
 * Inspect Ticket Tailor /discover page:
 * - Capture all XHR/fetch API calls
 * - Check if events appear in server HTML
 * - Find any internal API endpoints
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const apiCalls = [];

    // Intercept all network requests
    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        // Only capture API/JSON calls
        if (
            (ct.includes('json') || url.includes('/api/') || url.includes('/discover/')) &&
            !url.includes('google') && !url.includes('analytics') && !url.includes('hotjar') &&
            !url.includes('.css') && !url.includes('.js') && !url.includes('fonts')
        ) {
            try {
                const body = await resp.text().catch(() => '');
                apiCalls.push({
                    url,
                    status: resp.status(),
                    contentType: ct,
                    bodyPreview: body.substring(0, 500),
                });
            } catch (e) { /* ignore */ }
        }
    });

    console.log('Navigating to /discover...');
    await page.goto('https://www.tickettailor.com/discover', {
        waitUntil: 'networkidle2',
        timeout: 30000,
    });

    // Wait a bit more for lazy-loaded content
    await new Promise(r => setTimeout(r, 3000));

    // Check HTML for event data
    const htmlCheck = await page.evaluate(() => {
        const eventIds = [...document.querySelectorAll('[data-event-id]')].map(el => el.getAttribute('data-event-id'));
        const eventLinks = [...document.querySelectorAll('a[href*="/events/"]')].map(a => a.href).slice(0, 10);
        const title = document.title;
        const bodyText = document.body.innerText.substring(0, 500);
        // Check for next data
        const nextData = document.getElementById('__NEXT_DATA__');
        return {
            eventIds: eventIds.slice(0, 10),
            eventLinks,
            title,
            bodyPreview: bodyText,
            hasNextData: !!nextData,
            nextDataPreview: nextData ? nextData.textContent.substring(0, 300) : null,
        };
    });

    console.log('\n=== Page HTML check ===');
    console.log(JSON.stringify(htmlCheck, null, 2));

    console.log('\n=== API/JSON network calls ===');
    console.log(JSON.stringify(apiCalls, null, 2));

    // Now try the Philippines search
    console.log('\n=== Testing Philippines location search ===');
    const philSearch = [];
    page.on('response', async resp => {
        const url = resp.url();
        if (url.includes('api') || url.includes('search') || url.includes('discover')) {
            try {
                const body = await resp.text().catch(() => '');
                if (body.includes('"events"') || body.includes('"results"')) {
                    philSearch.push({ url, status: resp.status(), bodyPreview: body.substring(0, 600) });
                }
            } catch (e) { /* ignore */ }
        }
    });

    // Try searching for Philippines events
    await page.goto('https://www.tickettailor.com/discover?location=Philippines', {
        waitUntil: 'networkidle2',
        timeout: 30000,
    }).catch(() => {});

    await new Promise(r => setTimeout(r, 2000));

    const philHtml = await page.evaluate(() => {
        const links = [...document.querySelectorAll('a[href*="/events/"]')].map(a => a.href).slice(0, 10);
        return { eventLinks: links, bodyPreview: document.body.innerText.substring(0, 300) };
    });

    console.log('Philippines page HTML:', JSON.stringify(philHtml, null, 2));
    if (philSearch.length > 0) {
        console.log('Philippines API calls:', JSON.stringify(philSearch, null, 2));
    }

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
