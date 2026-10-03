/* Local, disposable acceptance database only. Requires Playwright and Edge. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const dependencies = process.env.DCT_NODE_MODULES || 'C:/Users/musta/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { chromium } = require(path.join(dependencies, 'playwright'));
const base = process.env.DCT_TEST_URL || 'http://127.0.0.1:18080';
assert.equal(base, 'http://127.0.0.1:18080', 'This script only targets the isolated local test server.');
const database = process.env.DCT_DB || process.env.DCT_TEST_DATABASE || 'dct_security_test_20261003';
const arabic = process.env.DCT_ARABIC === '1';
assert.match(database, /^dct_security_test_/);
const output = path.resolve(__dirname, '../.validation');
fs.mkdirSync(path.join(output, 'screenshots'), { recursive: true });
const fixture = JSON.parse(fs.readFileSync(path.join(output, 'fixture.json'), 'utf8'));
const summary = { database, base, locale: arabic ? 'ar' : 'en', started: new Date().toISOString(), checks: [], errors: [], assetFailures: [], externalRequests: [] };
let testingOfflineMap = false;

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.DCT_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    page.on('pageerror', error => summary.errors.push(error.message));
    page.on('console', message => {
        if (message.type() === 'error' && !(testingOfflineMap && message.location().url.startsWith('https://maps.example.invalid/'))) summary.errors.push(message.text());
    });
    page.on('response', response => { if (response.status() >= 400 && /\/web\/assets\//.test(response.url())) summary.assetFailures.push({ url: response.url(), status: response.status() }); });
    page.on('request', request => {
        if (/^https?:/.test(request.url()) && !request.url().startsWith(base) && !(testingOfflineMap && request.url().startsWith('https://maps.example.invalid/'))) summary.externalRequests.push(request.url());
    });
    const check = async (name, callback) => { await callback(); summary.checks.push(name); console.log(`PASS ${name}`); };
    const screenshot = async name => page.screenshot({ path: path.join(output, 'screenshots', name + '.png'), fullPage: true });
    const action = async name => {
        await page.goto(`${base}/odoo/action-dct_security_management.${name}`, { waitUntil: 'domcontentloaded' });
        await page.locator('.o_web_client').waitFor();
    };
    const rpc = async (model, method, args, kwargs = {}) => {
        const response = await page.request.post(`${base}/web/dataset/call_kw/${model}/${method}`, { data: { jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } } });
        const payload = await response.json();
        if (payload.error) throw new Error(JSON.stringify(payload.error));
        return payload.result;
    };
    try {
        await check('native login to isolated test database', async () => {
            await page.goto(`${base}/web/login?db=${encodeURIComponent(database)}`, { waitUntil: 'domcontentloaded' });
            await page.locator('input[name="login"]').fill(process.env.DCT_LOGIN || (arabic ? 'dct_arabic_acceptance' : 'admin'));
            await page.locator('input[name="password"]').fill(process.env.DCT_TEST_PASSWORD || 'dct-local-acceptance');
            await page.locator('button[type="submit"]').click();
            await page.locator('.o_web_client').waitFor();
        });
        if (arabic) {
            await check('Arabic dashboard direction, filters and drilldown', async () => {
                await action('action_dashboard');
                await page.locator('.dct_card').first().waitFor();
                assert.equal(await page.locator('.o_dct_security').evaluate(el => getComputedStyle(el).direction), 'rtl');
                assert.equal(await page.locator('.dct_card').count() >= 9, true);
                assert.match(await page.locator('.dct_header').innerText(), /[\u0600-\u06ff]/);
                await screenshot('overview-ar');
                const dates = page.locator('.dct_filters input[type="date"]');
                await dates.nth(0).fill('2026-09-01'); await dates.nth(1).fill('2026-10-31');
                await page.locator('.dct_filters select').last().selectOption(String(fixture.site));
                await page.locator('.dct_filters button.btn-primary').click();
                await page.locator('.dct_cards').first().waitFor();
                await screenshot('overview-filtered-ar');
                await page.locator('.dct_card').first().click();
                await page.locator('.o_list_view').waitFor();
                assert.match(await page.locator('.o_list_view').innerText(), /[\u0600-\u06ff]/);
            });
            await check('Arabic weekly board and calendar', async () => {
                await action('action_weekly_board'); await page.locator('.dct_week').waitFor();
                assert.equal(await page.locator('.dct_week').evaluate(el => getComputedStyle(el).direction), 'rtl');
                await screenshot('weekly-board-ar');
                await action('action_shift');
                await page.locator('.o_calendar_view,.o_list_view').first().waitFor();
                if (await page.locator('.o_switch_view.o_calendar').count()) await page.locator('.o_switch_view.o_calendar').click();
                await page.locator('.o_calendar_view').waitFor();
                await screenshot('calendar-ar');
            });
            await check('Arabic map fallback and finance forms', async () => {
                await action('action_site_map'); await page.locator('.dct_panel').waitFor();
                await screenshot('map-fallback-ar');
                for (const id of ['action_payroll', 'action_billing']) {
                    await action(id); await page.locator('.o_list_view').waitFor();
                    await page.locator('.o_data_row').first().locator('.o_data_cell').first().click();
                    await page.locator('.o_form_view').waitFor();
                    assert.equal(await page.locator('.o_form_view').evaluate(el => getComputedStyle(el).direction), 'rtl');
                    assert.equal(await page.locator('.o_field_monetary').count() > 0, true);
                    await screenshot(id + '-ar');
                }
            });
            await check('Arabic assets, JavaScript and external requests', async () => {
                assert.deepEqual(summary.assetFailures, []); assert.deepEqual(summary.errors, []); assert.deepEqual(summary.externalRequests, []);
            });
            summary.passed = true;
            return;
        }
        await check('connected dashboard cards and source drilldown', async () => {
            await action('action_dashboard');
            await page.locator('.dct_card').first().waitFor();
            assert.equal(await page.locator('.dct_card').count() >= 9, true);
            assert.match(await page.locator('.dct_card').first().innerText(), /Guards/);
            assert.equal(await page.locator('.o_dct_security [role="alert"]').count(), 0);
            await screenshot('overview-en');
            await page.locator('.dct_card').first().click();
            await page.locator('.o_list_view').waitFor();
            assert.match(await page.locator('.o_list_view').innerText(), /Guard Normal/);
        });
        await check('dashboard date and site filters', async () => {
            await action('action_dashboard');
            await page.locator('.dct_card').first().waitFor();
            const dates = page.locator('.dct_filters input[type="date"]');
            await dates.nth(0).fill('2026-09-01'); await dates.nth(1).fill('2026-10-31');
            await page.locator('.dct_filters select').last().selectOption(String(fixture.site));
            await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
            await page.locator('.dct_cards').first().waitFor();
            await page.getByText('2026-09-01 — 2026-10-31', { exact: false }).waitFor();
            assert.equal(await page.locator('.o_dct_security [role="alert"]').count(), 0);
            await screenshot('overview-filtered-en');
        });
        await check('weekly board guard rows, draft form and existing shift', async () => {
            await action('action_weekly_board');
            await page.locator('.dct_week').waitFor();
            assert.match(await page.locator('.dct_week').innerText(), /Guard Normal/);
            await screenshot('weekly-board-en');
            await page.locator('.dct_add').first().click();
            await page.locator('.modal .o_form_view').waitFor();
            assert.equal(await page.locator('.modal input[id^="start_"]').count() > 0 || await page.locator('.modal [name="start"]').count() > 0, true);
            await page.locator('.modal .btn-close').click();
            if (await page.locator('.dct_shift').count()) {
                await page.locator('.dct_shift').first().click();
                await page.locator('.o_form_view').waitFor();
                assert.match(await page.locator('.o_form_view').innerText(), /Published|Draft/);
            }
        });
        await check('native shift calendar', async () => {
            await action('action_shift');
            await page.locator('.o_calendar_view,.o_list_view').first().waitFor();
            const switcher = page.locator('.o_switch_view.o_calendar');
            if (await switcher.count()) await switcher.click();
            await page.locator('.o_calendar_view').waitFor();
            await screenshot('calendar-en');
        });
        await check('unconfigured map remains usable with no external requests', async () => {
            await action('action_site_map');
            await page.getByText('No map tile provider is configured.', { exact: false }).waitFor();
            assert.match(await page.locator('.dct_panel').innerText(), /Fictional Acceptance Campus/);
            await screenshot('map-fallback-en');
        });
        await check('configured map pins, attribution and offline list fallback', async () => {
            const saved = (await rpc('res.company', 'read', [[fixture.company], ['dct_map_tile_url', 'dct_map_attribution']]))[0];
            testingOfflineMap = true;
            let intercepted = 0;
            await page.route('https://maps.example.invalid/**', route => { intercepted += 1; return route.abort(); });
            try {
                await rpc('res.company', 'write', [[fixture.company], { dct_map_tile_url: 'https://maps.example.invalid/{z}/{x}/{y}.png', dct_map_attribution: 'Fictional acceptance tiles' }]);
                await action('action_site_map');
                await page.locator('.leaflet-container').waitFor();
                await page.getByText('Map tiles could not be loaded.', { exact: false }).waitFor();
                assert.match(await page.locator('.leaflet-control-attribution').innerText(), /Fictional acceptance tiles/);
                assert.equal(await page.locator('.leaflet-interactive').count(), 1);
                assert.match(await page.locator('.dct_panel').innerText(), /33\.3152/);
                await page.locator('.leaflet-interactive').click();
                await page.locator('.leaflet-popup').waitFor();
                await page.waitForFunction(() => [...document.querySelectorAll('.leaflet-popup')].every(el => getComputedStyle(el).opacity === '1'));
                assert.match(await page.locator('.leaflet-popup').innerText(), /Fictional Acceptance Campus/);
                assert.equal(intercepted > 0, true);
                summary.interceptedTileRequests = intercepted;
                await screenshot('map-configured-offline-en');
            } finally {
                await rpc('res.company', 'write', [[fixture.company], { dct_map_tile_url: saved.dct_map_tile_url, dct_map_attribution: saved.dct_map_attribution }]);
                await action('action_site_map');
                await page.locator('.dct_panel').waitFor();
                await page.unroute('https://maps.example.invalid/**');
                testingOfflineMap = false;
            }
        });
        const forms = [
            ['action_guard', 'Guards'], ['action_site', 'Sites'], ['action_contract', 'Contracts'],
            ['action_assignment', 'Assignments'], ['action_attendance', 'Attendance'],
            ['action_patrol', 'Patrols'], ['action_incident', 'Incidents'], ['action_visit', 'Visits'],
            ['action_payroll', 'Payroll'], ['action_billing', 'Billing'],
        ];
        for (const [id, label] of forms) await check(`native ${label} list and record`, async () => {
            await action(id);
            await page.locator('.o_list_view,.o_kanban_view').first().waitFor();
            if (await page.locator('.o_kanban_view').count()) await page.locator('.o_switch_view.o_list').click();
            await page.locator('.o_list_view').waitFor();
            const rows = page.locator('.o_data_row');
            if (await rows.count()) {
                await rows.first().locator('.o_data_cell').first().click();
                await page.locator('.o_form_view').waitFor();
                assert.equal(await page.locator('.o_error_dialog').count(), 0);
            }
        });
        await check('asset and JavaScript errors', async () => {
            assert.deepEqual(summary.assetFailures, []);
            assert.deepEqual(summary.errors, []);
            assert.deepEqual(summary.externalRequests, []);
        });
        summary.passed = true;
    } catch (error) {
        summary.passed = false; summary.failure = error.stack;
        await screenshot('failure').catch(() => {});
        console.error(error.stack);
        process.exitCode = 1;
    } finally {
        summary.finished = new Date().toISOString();
        fs.writeFileSync(path.join(output, arabic ? 'browser-results-ar.json' : 'browser-results.json'), JSON.stringify(summary, null, 2));
        await browser.close();
    }
})();
