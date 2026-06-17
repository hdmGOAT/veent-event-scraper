/**
 * Read the AllEvents Azure APIM developer portal to discover API endpoint docs.
 * Portal renders as SPA — needs Puppeteer to execute JS.
 */
import { getBrowser, getPage, disconnectBrowser } from '../../../.claude/skills/vc-chrome-devtools/scripts/lib/browser.js';

async function main() {
    const browser = await getBrowser({ headless: true });
    const page = await getPage(browser);

    const apiResponses = [];
    await page.setRequestInterception(true);
    page.on('request', req => req.continue());
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        if (ct.includes('json') || url.includes('/apis') || url.includes('/operations')) {
            try {
                const body = await resp.text().catch(() => '');
                if (body.length > 10 && body.length < 50000) {
                    apiResponses.push({ url, status: resp.status(), ct, preview: body.substring(0, 1000) });
                }
            } catch (_) {}
        }
    });

    // Load the APIs list page
    console.log('Loading developer portal /apis...');
    await page.goto('https://allevents.developer.azure-api.net/apis', {
        waitUntil: 'networkidle2',
        timeout: 30000,
    });
    await new Promise(r => setTimeout(r, 3000));

    const apisPage = await page.evaluate(() => ({
        title: document.title,
        text: document.body.innerText.substring(0, 3000),
        links: [...document.querySelectorAll('a[href]')].map(a => ({ text: a.innerText.trim(), href: a.href })).filter(l => l.text),
    }));

    console.log('\n=== APIs page ===');
    console.log('Title:', apisPage.title);
    console.log('Text:', apisPage.text);
    console.log('\nLinks:');
    apisPage.links.forEach(l => console.log(`  [${l.text}] ${l.href}`));

    // Click on first API link if available
    const apiLinks = apisPage.links.filter(l => l.href.includes('/apis/'));
    if (apiLinks.length > 0) {
        console.log('\n=== Clicking API link:', apiLinks[0].href, '===');
        await page.goto(apiLinks[0].href, { waitUntil: 'networkidle2', timeout: 20000 });
        await new Promise(r => setTimeout(r, 2000));

        const apiDetail = await page.evaluate(() => ({
            title: document.title,
            text: document.body.innerText.substring(0, 5000),
        }));
        console.log('API detail title:', apiDetail.title);
        console.log('API detail text:', apiDetail.text);
    }

    console.log('\n=== Network API responses captured ===');
    apiResponses.forEach(r => console.log(`  [${r.status}] ${r.url}\n    ${r.preview.substring(0, 300)}\n`));

    await disconnectBrowser();
}

main().catch(err => { console.error('Error:', err.message); process.exit(1); });
