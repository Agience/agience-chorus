import { test, expect, type Page } from '@playwright/test';

/**
 * The page takes its width from the viewport.
 *
 * At 390 px (a phone) and 1280 px (a laptop): nothing scrolls sideways, and Share and Help sit
 * inside the window. Below 640 px one panel shows at a time and the top bar switches between them.
 *
 * Signs in as the node-local `e2e-facet` account; see `signed-in.e2e.ts` for how to create it.
 */
const EMAIL = process.env.FACET_E2E_EMAIL ?? 'e2e-facet';
const PASSWORD = process.env.FACET_E2E_PASSWORD;
if (!PASSWORD) {
  throw new Error('FACET_E2E_PASSWORD is not set. Set it to the e2e-facet account\'s password.');
}

async function signIn(page: Page) {
  await page.goto('/');
  if (page.url().includes('/setup')) {
    throw new Error('this node reports needs_setup — run the wizard, or point the suite at a configured node');
  }
  await page.locator('#identifier').fill(EMAIL);
  await page.locator('#identifier').press('Enter');
  const password = page.locator('#password');
  await expect(password).toBeVisible();
  await password.fill(PASSWORD!);
  await password.press('Enter');
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
  await expect(page.locator('header')).toBeVisible();
}

async function assertFits(page: Page) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(scrollWidth, 'the page scrolls sideways').toBeLessThanOrEqual(innerWidth);
  for (const name of ['Open help', 'Share workspace']) {
    const control = page.getByRole('button', { name }).first();
    if (!(await control.count())) continue; // Share shows only with a workspace open
    const box = await control.boundingBox();
    expect(box, `${name} is not laid out`).not.toBeNull();
    expect(box!.x + box!.width, `${name} runs past the window`).toBeLessThanOrEqual(innerWidth);
  }
}

for (const size of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
  test(`fits the window at ${size.width} px`, async ({ page }) => {
    await page.setViewportSize(size);
    await signIn(page);
    await assertFits(page);
  });
}

test('a phone shows one panel and switches between them', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await expect(page.locator('#right-panel')).toBeVisible();
  await expect(page.locator('#left-panel')).toBeHidden();

  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.locator('#left-panel')).toBeVisible();
  await expect(page.locator('#right-panel')).toBeHidden();

  await page.getByRole('button', { name: 'More' }).click();
  await expect(page.getByRole('menuitem', { name: 'Trash' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Settings' })).toBeVisible();
});

/** Every visible button whose centre lands on something else, named for the failure message. */
async function coveredButtons(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const covered: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('button, [role="button"]'))) {
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height || el.closest('[hidden], [inert], [aria-hidden="true"]')) continue;
      const x = box.left + box.width / 2;
      const y = box.top + box.height / 2;
      if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) continue;
      const hit = document.elementFromPoint(x, y);
      if (hit && !el.contains(hit)) {
        covered.push(el.getAttribute('aria-label') || el.title || el.textContent?.trim() || el.tagName);
      }
    }
    return covered;
  });
}

test('no control on a phone is drawn under another', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  expect(await coveredButtons(page), 'covered in the workspace panel').toEqual([]);

  await page.getByRole('button', { name: 'Search', exact: true }).click();
  expect(await coveredButtons(page), 'covered in the search panel').toEqual([]);

  await page.getByRole('button', { name: 'Workspace', exact: true }).click();
  const dock = page.getByRole('button', { name: 'Dock a workspace' });
  if (await dock.count()) {
    await dock.first().click();
    const first = page.getByRole('menuitem').first();
    await expect(first).toBeVisible();
    await first.click();
  }
});
